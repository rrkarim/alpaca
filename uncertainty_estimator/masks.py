from collections import defaultdict

import torch
from torch.autograd import Variable
from pyDOE import lhs
import numpy as np
from scipy.special import softmax
from dppy.finite_dpps import FiniteDPP


DEFAULT_MASKS = ['vanilla', 'mirror_random', 'decorrelating', 'decorrelating_sc', 'adpp']


def build_masks(names=None, nn_runs=100):
    masks = {
        'vanilla': None,
        'basic_mask': BasicMask(),
        'lhs': LHSMask(nn_runs),
        'lhs_shuffled': LHSMask(nn_runs, shuffle=True),
        'mirror_random': MirrorMask(),
        'decorrelating': DecorrelationMask(),
        'decorrelating_sc': DecorrelationMask(scaling=True, dry_run=False),
        'dpp': DPPMask(),
        'adpp': DPPAdaptiveMask()
    }
    if names is None:
        return masks
    return {name: masks[name] for name in names}


class BasicMask:
    def __call__(self, x, dropout_rate=0.5, layer_num=0):
        p = 1 - dropout_rate
        mask = x.data.new(x.data.size()[-1]).fill_(0)
        nonzero_count = round(len(mask)*p)
        mask[np.random.permutation(len(mask))[:nonzero_count]] = 1
        mask = mask * (len(mask)/(nonzero_count + 1e-10))

        return mask


class LHSMask:
    def __init__(self, nn_runs=25, shuffle=False):
        self.nn_runs = nn_runs
        self.layer_masks = {}
        self.shuffle = shuffle

    def __call__(self, x, dropout_rate=0.5, layer_num=0):
        if layer_num not in self.layer_masks:
            masks = lhs(n=x.shape[-1], samples=self.nn_runs)
            if self.shuffle:
                np.random.shuffle(masks)
            self.layer_masks[layer_num] = iter(masks)
        mask = next(self.layer_masks[layer_num])
        mask = (mask > dropout_rate).astype('float') / (1-dropout_rate+1e-10)
        return x.data.new(mask)

    def reset(self):
        self.layer_masks = {}


class MirrorMask:
    def __init__(self):
        self.layer_masks = defaultdict(list)

    def __call__(self, x, dropout_rate=0.5, layer_num=0):
        if not self.layer_masks[layer_num]:
            next_couple = self._generate_couple(x, dropout_rate)
            self.layer_masks[layer_num].extend(next_couple)
        return self.layer_masks[layer_num].pop()

    def _generate_couple(self, x, dropout_rate):
        p = 1 - dropout_rate
        probability_tensor = x.data.new(x.data.size()[-1]).fill_(p)
        mask_1 = torch.bernoulli(probability_tensor)
        mask_2 = (x.data.new(x.data.size()[-1]).fill_(1) - mask_1) / (1 - p + 1e-10)
        mask_1 = mask_1 / (p + 1e-10)

        return [mask_1, mask_2]


class DecorrelationMask:
    def __init__(self, scaling=False, dry_run=True):
        self.layer_correlations = {}
        self.scaling = scaling  # use adaptive scaling before softmax
        self.dry_run = dry_run

    def __call__(self, x, dropout_rate=0.5, layer_num=0):
        if layer_num not in self.layer_correlations:
            x_matrix = x.cpu().numpy()
            corrs = np.sum(np.abs(np.corrcoef(x_matrix.T)), axis=1)
            scores = np.reciprocal(corrs)
            if self.scaling:
                scores = 4 * scores / max(scores)
            self.layer_correlations[layer_num] = softmax(scores)
            # Initially we should pass identity mask,
            # otherwise we won't get right correlations for all layers
            return x.data.new(x.data.size()[-1]).fill_(1)
        mask = x.data.new(x.data.size()[-1]).fill_(0)
        k = int(len(mask)*(1-dropout_rate))
        ids = np.random.choice(len(mask), k, p=self.layer_correlations[layer_num])
        mask[ids] = 1 / (1 - dropout_rate + 1e-10)

        return x.data.new(mask)

    def reset(self):
        self.layer_correlations = {}


class DPPMask:
    def __init__(self, dry_run=True):
        self.layer_correlations = {}
        self.dry_run = dry_run
        self.dpps = {}

    def __call__(self, x, dropout_rate=0.5, layer_num=0):
        if layer_num not in self.layer_correlations:
            x_matrix = x.cpu().numpy()
            correlations = np.abs(np.corrcoef(x_matrix.T))
            self.dpps[layer_num] = FiniteDPP('likelihood', **{'L': correlations})
            self.layer_correlations[layer_num] = correlations
            return x.data.new(x.data.size()[-1]).fill_(1)

        mask = x.data.new(x.data.size()[-1]).fill_(0)
        k = int(len(mask) * (1 - dropout_rate))
        dpp = self.dpps[layer_num]
        dpp.sample_exact_k_dpp(k)
        ids = dpp.list_of_samples[-1]

        mask[ids] = 1 / (1 - dropout_rate + 1e-10)

        return x.data.new(mask)

    def reset(self):
        self.layer_correlations = {}


class DPPAdaptiveMask:
    def __init__(self, dry_run=True):
        self.layer_correlations = {}
        self.dry_run = dry_run
        self.dpps = {}
        self.ranks = {}

    def _rank(self, dpp):
        N = dpp.eig_vecs.shape[0]
        tol = np.max(dpp.L_eig_vals) * N * np.finfo(np.float).eps
        rank = np.count_nonzero(dpp.L_eig_vals > tol)
        return rank

    def __call__(self, x, dropout_rate=0.5, layer_num=0):
        if layer_num not in self.layer_correlations:
            x_matrix = x.cpu().numpy()
            self.layer_correlations[layer_num] = np.abs(np.corrcoef(x_matrix.T))
            self.dpps[layer_num] = FiniteDPP('correlation', **{'K': self.layer_correlations[layer_num]})
            self.dpps[layer_num].sample_exact_k_dpp(1)  # to trigger eig values generation
            self.ranks[layer_num] = self._rank(self.dpps[layer_num])
            return x.data.new(x.data.size()[-1]).fill_(1)

        mask = x.data.new(x.data.size()[-1]).fill_(0)
        k = int(self.ranks[layer_num] * (1 - dropout_rate))
        self.dpps[layer_num].sample_exact_k_dpp(k)
        ids = self.dpps[layer_num].list_of_samples[-1]

        mask[ids] = 1 / (1 - dropout_rate + 1e-10)

        return x.data.new(mask)

    def reset(self):
        self.layer_correlations = {}
