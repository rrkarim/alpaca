import torch
import torch.nn as nn
import torch.nn.functional as F


class SimpleConv(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 16, 3)
        self.conv2 = nn.Conv2d(16, 32, 3)
        self.linear_size = 12*12*32
        self.fc1 = nn.Linear(self.linear_size, 256)
        self.dropout = nn.Dropout(0.5)
        self.fc2 = nn.Linear(256, 10)

    def forward(self, x, dropout_rate=0., dropout_mask=None):
        x = F.elu(self.conv1(x))
        x = F.elu(self.conv2(x))
        x = F.max_pool2d(x, 2, 2)
        x = x.view(-1, self.linear_size)
        # x = self._dropout(x, dropout_mask, dropout_rate, 0)
        x = F.elu(self.fc1(x))
        x = self._dropout(x, dropout_mask, dropout_rate, 1)
        x = self.fc2(x)
        return x

    def _dropout(self, x, dropout_mask, dropout_rate, layer_num):
        if dropout_mask is None:
            x = self.dropout(x)
        else:
            x = x * dropout_mask(x, dropout_rate, layer_num)
        return x


class MediumConv(nn.Module):
    def __init__(self, dropout_rate=0.5):
        super().__init__()
        kernels = 20
        self.conv1 = nn.Conv2d(3, kernels, 3)
        self.conv2 = nn.Conv2d(kernels, 2*kernels, 3)
        self.dropout_0 = nn.Dropout(0.25)
        self.linear_size = 14*14*(2*kernels)
        self.fc1 = nn.Linear(self.linear_size, 256)
        self.dropout = nn.Dropout(dropout_rate)
        self.fc2 = nn.Linear(256, 128)
        self.fc3 = nn.Linear(128, 10)

    def forward(self, x, dropout_rate=0., dropout_mask=None):
        x = F.elu(self.conv1(x))
        x = F.elu(self.conv2(x))
        x = F.max_pool2d(x, 2, 2)
        x = x.view(-1, self.linear_size)
        x = self.dropout_0(x)
        x = F.elu(self.fc1(x))
        x = self._dropout(x, dropout_mask, dropout_rate, 0)
        x = F.elu(self.fc2(x))
        x = self._dropout(x, dropout_mask, dropout_rate, 1)
        x = self.fc3(x)
        return x

    def _dropout(self, x, dropout_mask, dropout_rate, layer_num):
        if dropout_mask is None:
            x = self.dropout(x)
        else:
            x = x * dropout_mask(x, dropout_rate, layer_num)
        return x
