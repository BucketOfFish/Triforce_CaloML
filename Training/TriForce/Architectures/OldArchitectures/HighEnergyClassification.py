import torch
from torch.autograd import Variable
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import math, pdb
from Architectures import LossFunctions

##################
# Classification #
##################

CLASSIFICATION, REGRESSION = 0, 1

class Classifier_Net(nn.Module):

    def __init__(self, options):
        super().__init__()
        # settings
        self.windowSizeECAL = options['windowSizeECAL']
        self.windowSizeHCAL = options['windowSizeHCAL']
        self.nHiddenLayers = options['nHiddenLayers']
        hiddenLayerNeurons = options['hiddenLayerNeurons']
        self.outputs = []
        for particle_class in options['classPdgID']:
            self.outputs += [(str(particle_class)+"_classification", CLASSIFICATION)]
        self.outputs += [("energy_regression", REGRESSION), ("eta_regression", REGRESSION), ("phi_regression", REGRESSION)]
        # layers
        ECAL_size = self.windowSizeECAL * self.windowSizeECAL * 25
        HCAL_size = self.windowSizeHCAL * self.windowSizeHCAL * 60
        nsums = 2 if self.windowSizeHCAL > 0 else 1
        self.input = nn.Linear(ECAL_size + HCAL_size + nsums, hiddenLayerNeurons)
        self.hidden = nn.ModuleList()
        self.dropout = nn.ModuleList()
        for i in range(self.nHiddenLayers):
            self.hidden.append(nn.Linear(hiddenLayerNeurons, hiddenLayerNeurons))
            self.dropout.append(nn.Dropout(p = options['dropoutProb']))
        self.finalLayer = nn.Linear(hiddenLayerNeurons + nsums, len(self.outputs)) # nClasses = 2 for binary classifier
        # initialize weights for energy sums in energy output to 1: assume close to identity
        energy_index = self.outputs.index(("energy_regression", REGRESSION))
        output_params = self.finalLayer.weight.data
        output_params[energy_index][-1] = 1.0
        if nsums > 1: output_params[energy_index][-2] = 1.0

    def forward(self, data):
        # ECAL slice and energy sum
        ECAL = Variable(data["ECAL"].cuda())
        lowerBound = 26 - int(math.ceil(self.windowSizeECAL/2))
        upperBound = lowerBound + self.windowSizeECAL
        ECAL = ECAL[:, lowerBound:upperBound, lowerBound:upperBound]
        ECAL = ECAL.contiguous().view(-1, self.windowSizeECAL * self.windowSizeECAL * 25)
        ECAL_sum = torch.sum(ECAL, dim = 1).view(-1, 1)
        # HCAL slice and energy sum
        if (self.windowSizeHCAL > 0):
            HCAL = Variable(data["HCAL"].cuda())
            lowerBound = 6 - int(math.ceil(self.windowSizeHCAL/2))
            upperBound = lowerBound + self.windowSizeHCAL
            HCAL = HCAL[:, lowerBound:upperBound, lowerBound:upperBound]
            HCAL = HCAL.contiguous().view(-1, self.windowSizeHCAL * self.windowSizeHCAL * 60)
            HCAL_sum = torch.sum(HCAL, dim = 1).view(-1, 1)
            x = torch.cat([ECAL, HCAL, ECAL_sum, HCAL_sum], 1)
        else:
            x = torch.cat([ECAL, ECAL_sum], 1)
        # feed forward
        x = self.input(x)
        for i in range(self.nHiddenLayers):
            x = F.relu(self.hidden[i](x))
            x = self.dropout[i](x)
        # cat energy sums back in before final layer
        if (self.windowSizeHCAL > 0):
            x = torch.cat([x, ECAL_sum, HCAL_sum], 1)
        else:
            x = torch.cat([x, ECAL_sum], 1)
        x = self.finalLayer(x)
        # preparing output
        return_data = {}
        for i, (label, activation) in enumerate(self.outputs):
            if activation == CLASSIFICATION:
                if 'classification' in return_data.keys():
                    return_data['classification'] = torch.stack((return_data['classification'], x[:, i]))
                else:
                    return_data['classification'] = x[:, i]
            else:
                return_data[label] = x[:, i]
        return_data['classification'] = F.softmax(return_data['classification'].transpose(0, 1), dim=1)
        return return_data

class Net():
    def __init__(self, options):
        self.net = Classifier_Net(options)
        self.net.cuda()
        self.optimizer = optim.Adam(self.net.parameters(), lr=options['learningRate'], weight_decay=options['decayRate'])
        self.lossFunction = LossFunctions.combinedLossFunction
