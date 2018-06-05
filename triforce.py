################################################################
#  ##########################################################  #
#  #                                                        #  #
#  #      /\\     TRIFORCE PARTICLE IDENTIFICATION SYSTEM   #  #
#  #     /__\\    Classification, Energy Regression & GAN   #  #
#  #    /\\ /\\                                             #  #
#  #   /__\/__\\                       Run using Python 3   #  #
#  #                                                        #  #
#  ##########################################################  #
################################################################

import torch
import torch.utils.data as data
from torch.autograd import Variable
import glob, os, sys, shutil
import numpy as np
import h5py as h5
import Loader.loader as loader
from triforce_helper_functions import *
import Options
sys.dont_write_bytecode = True # prevent the creation of .pyc files

####################
# Set options file #
####################

optionsFileName = "fixed_angle_new_samples"

######################################################
# Import options & warn if options file has problems #
######################################################

# load options
exec("from Options." + optionsFileName + " import *")

# options file must have these parameters set
requiredOptionNames = ['samplePath', 'classPdgID', 'trainRatio', 'nEpochs', 'batchSize', 'outPath']
for optionName in requiredOptionNames:
    if optionName not in options.keys():
        print("ERROR: Please set", optionName, "in options file")
        sys.exit()

# if these parameters are not set, give them default values
defaultParameters = {'importGPU':False, 'eventsPerFile':10000, 'nTrainMax':-1, 'nValidationMax':-1, 'nTestMax':-1, 'validationRatio':0, 'nWorkers':0, 'calculate_loss_per_n_batches':20, 'test_loss_eval_max_n_batches':10, 'earlyStopping':False, 'relativeDeltaLossThreshold':0, 'relativeDeltaLossNumber':5, 'saveModelEveryNEpochs':0, 'saveFinalModel':0}
for optionName in defaultParameters.keys():
    if optionName not in options.keys():
        options[optionName] = defaultParameters[optionName]

# for Caltech GPU cluster
if (options['importGPU']):
    import setGPU

# if validation parameters are not set, TriForce will use test set as validation set
if options['validationRatio'] + options['trainRatio'] >= 1:
    print("ERROR: validationRatio and/or trainRatio is too high")

# warn if output directory already exists
if not os.path.exists(options['outPath']):
    os.makedirs(options['outPath'])
else:
    print("WARNING: Output directory already exists - overwrite (y/n)?")
    valid = {"yes": True, "y": True, "ye": True, "no": False, "n": False}
    while True:
        choice = input().lower()
        if choice in valid:
            overwrite = valid[choice]
            break
        else:
            print("Please respond with 'yes' or 'no'")
    if overwrite:
        shutil.rmtree(options['outPath'])
        os.makedirs(options['outPath'])
    else:
        sys.exit()

# copy code to output directory for logging purposes
optionsFilePath = Options.__file__[:Options.__file__.rfind('/')]
shutil.copyfile(optionsFilePath + "/" + optionsFileName + ".py", options['outPath']+"/options.py")
shutil.copyfile(optionsFilePath + "/../triforce.py", options['outPath']+"/triforce.py")

####################################
# Load files and set up generators #
####################################

print('-------------------------------')
print('Loading Files')

# gather sample files for each type of particle
nClasses = len(options['samplePath'])
classFiles = [[]] * nClasses
for i, classPath in enumerate(options['samplePath']):
    classFiles[i] = glob.glob(classPath)

# determine numbers of test, train, and validation files
filesPerClass = min([len(files) for files in classFiles])
nTrain = int(filesPerClass * options['trainRatio'])
nValidation = int(filesPerClass * options['validationRatio'])
nTest = filesPerClass - nTrain - nValidation
if (options['validationRatio'] > 0):
    print("Split (files per class): %d train, %d test, %d validation" % (nTrain, nTest, nValidation))
else:
    print("Split (files per class): %d train, %d test" % (nTrain, nTest))
if options['nTrainMax']>0:
    nTrain = min(nTrain,options['nTrainMax'])
if options['nValidationMax']>0:
    nValidation = min(nValidation,options['nValidationMax'])
if options['nTestMax']>0:
    nTest = min(nTest,options['nTestMax'])
if (nTest==0 or nTrain==0 or (options['validationRatio']>0 and nValidation==0)):
    print("Not enough files found - check sample paths")
print('-------------------------------')

# split the train, test, and validation files
trainFiles = []
validationFiles = []
testFiles = []
for i in range(filesPerClass):
    newFiles = []
    for j in range(nClasses):
        newFiles.append(classFiles[j][i])
    if i < nTrain:
        trainFiles.append(newFiles)
    elif i < nTrain + nValidation:
        validationFiles.append(newFiles)
    elif i < nTrain + nValidation + nTest:
        testFiles.append(newFiles)
    else:
        break
if options['validationRatio'] == 0:
    validationFiles = testFiles

# prepare the generators
trainSet = loader.HDF5Dataset(trainFiles, options['eventsPerFile']*nClasses, options['classPdgID'])
validationSet = loader.HDF5Dataset(validationFiles, options['eventsPerFile']*nClasses, options['classPdgID'])
testSet = loader.HDF5Dataset(testFiles, options['eventsPerFile']*nClasses, options['classPdgID'])
trainLoader = data.DataLoader(dataset=trainSet,batch_size=options['batchSize'],sampler=loader.OrderedRandomSampler(trainSet),num_workers=options['nWorkers'])
validationLoader = data.DataLoader(dataset=validationSet,batch_size=options['batchSize'],sampler=loader.OrderedRandomSampler(validationSet),num_workers=options['nWorkers'])
testLoader = data.DataLoader(dataset=testSet,batch_size=options['batchSize'],sampler=loader.OrderedRandomSampler(testSet),num_workers=options['nWorkers'])

################################################
# Data structures for holding training results #
################################################

class historyData(list):
    def __init__(self, my_list=[]):
        super().__init__(my_list)
    def extend(self, places):
        for _ in range(places):
            self.append(historyData())
    def __getitem__(self, key): # overloads list[i] for i out of range
        if key >= len(self):
            self.extend(key+1-len(self))
        return super().__getitem__(key)
    def __setitem__(self, key, item): # overloads list[i]=x for i out of range
        if key >= len(self):
            self.extend(key+1-len(self))
        super().__setitem__(key, item)
    def __iadd__(self, key): # overloads []+=x
        return key
    def __add__(self, key): # overloads []+x
        return key

# training results e.g. history[LOSS][CLASSIFICATION][TRAIN][EPOCH]
history = historyData()

# enumerate parts of the data structure
stat_name = ['loss', 'accuracy', 'signalAccuracy', 'backgroundAccuracy']
LOSS, ACCURACY, SIGNAL_ACCURACY, BACKGROUND_ACCURACY = 0, 1, 2, 3
tools = [classifier, regressor, GAN]
tool_name = ['classifier', 'regressor', 'GAN']
tool_letter = ['C', 'R', 'G']
CLASSIFICATION, REGRESSION, _GAN = 0, 1, 2
split_name = ['train', 'validation', 'test']
TRAIN, VALIDATION, TEST = 0, 1, 2
timescale_name = ['batch', 'epoch']
BATCH, EPOCH = 0, 1

#########
# Train #
#########

# # determine when to end training
# previous_total_test_loss = 0
# previous_epoch_total_test_loss = 0
# end_training = False
# delta_loss_below_threshold_count = 0

# def update_test_loss(epoch_end=False):
    
    # # find the current test stats e.g. test_stats[LOSS][GAN]
    # test_stats = [[0]*3 for _ in range(4)]
    # stat_index = [0, 1, 6, 7] # return indices for eval()
    # for n_test_batches, data in enumerate(validationLoader):
        # ECALs, HCALs, ys, energies, etas = data
        # ECALs, HCALs, ys, energies, etas = Variable(ECALs.cuda()), Variable(HCALs.cuda()), Variable(ys.cuda()), Variable(energies.cuda()), Variable(etas.cuda())
        # for tool in range(len(tools)):
            # if (tools[tool] != None):
                # eval_results = eval(tools[tool], ECALs, HCALs, ys)
                # for stat in range(len(stat_name)):
                    # test_stats[stat][tool] += eval_results[stat_index[stat]] 
        # if (n_test_batches >= options['test_loss_eval_max_n_batches']):
            # break
    # for stat_index, test_stat in enumerate(test_stats):
        # test_stats[stat_index] = [i/(n_test_batches+1) for i in test_stat]

    # # print test loss and accuracy to screen
    # print_prefix = ""
    # if (epoch_end):
        # print("-------------------------------")
        # print_prefix = "epoch "
    # print(print_prefix + 'test loss:\t', end="")
    # for tool in range(len(tools)):
        # if (tools[tool] != None): print('(' + tool_letter[tool] + ') %.4f\t' % (test_stats[LOSS][tool]), end="")
    # print(print_prefix + 'test accuracy:\t', end="")
    # for tool in range(len(tools)):
        # if (tools[tool] != None): print('(' + tool_letter[tool] + ') %.4f\t' % (test_stats[ACCURACY][tool]), end="")
    # print()

    # # save test stats
    # for tool in range(len(tools)):
        # if (tools[tool] != None):
            # for stat in range(len(stat_name)):
                # history[stat][tool][TEST][BATCH].append(test_stats[stat][tool])
                # if (epoch_end): history[stat][tool][TEST][EPOCH].append(test_stats[stat][tool])

    # # decide whether or not to end training when this epoch finishes
    # global previous_total_test_loss, previous_epoch_total_test_loss, delta_loss_below_threshold_count, end_training
    # total_test_loss = 0
    # for tool in range(len(tools)):
        # if (tools[tool] != None): total_test_loss += test_stats[LOSS][tool]
    # relative_delta_loss = 1 if previous_total_test_loss==0 else (previous_total_test_loss - total_test_loss)/(previous_total_test_loss)
    # previous_total_test_loss = total_test_loss
    # if (relative_delta_loss < options['relativeDeltaLossThreshold']): delta_loss_below_threshold_count += 1
    # else: delta_loss_below_threshold_count = 0
    # if (delta_loss_below_threshold_count >= options['relativeDeltaLossNumber']):
        # if(options['earlyStopping']): end_training = True
    # if (epoch_end):
        # epoch_total_test_loss = test_stats[LOSS][CLASSIFICATION] + test_stats[LOSS][REGRESSION] + test_stats[LOSS][_GAN]
        # relative_delta_loss = 1 if previous_epoch_total_test_loss==0 else (previous_epoch_total_test_loss - epoch_total_test_loss)/(previous_epoch_total_test_loss)
        # previous_epoch_total_test_loss = epoch_total_test_loss
        # if (relative_delta_loss < options['relativeDeltaLossThreshold']):
            # if(options['earlyStopping']): end_training = True

print('Training')

total_batch_n = 0
saved_batch_n = 0

def update_batch_history(data_train, data_test, epoch_end=False):
    train_ECALs, train_HCALs, train_ys, train_energies, train_etas = data_train
    test_ECALs, test_HCALs, test_ys, test_energies, test_etas = data_test
    for tool in range(len(tools)):
        if (tools[tool] != None):
            for split in [TRAIN, TEST]:
                if split == TRAIN and not epoch_end:
                    eval_results = train(tools[tool], Variable(train_ECALs.cuda()), Variable(train_HCALs.cuda()), Variable(train_ys.cuda()))
                else:
                    eval_results = eval(tools[tool], Variable(test_ECALs.cuda()), Variable(test_HCALs.cuda()), Variable(test_ys.cuda()))
                for stat in range(2):
                    history[stat][tool][split][BATCH][saved_batch_n] += eval_results[stat] 
                    if total_batch_n % options['calculate_loss_per_n_batches'] == 0:
                        history[stat][tool][split][BATCH][saved_batch_n] /= options['calculate_loss_per_n_batches']

def print_stats(timescale):
    print_prefix = ""
    if (epoch_end): print_prefix = "epoch "
    print('-------------------------------')
    print('epoch %d, batch %d' % (epoch+1, total_batch_n))
    for split in [TRAIN, TEST]:
        for stat in [LOSS, ACCURACY]:
            print(print_prefix + split_name[split] + ' ' + stat_name[stat] + ':\t', end="")
            for tool in range(len(tools)):
                if (tools[tool] != None): print('(' + tool_letter[tool] + ') %.4f\t' % (history[stat][tool][split][timescale][-1]), end="")
        print()

for epoch in range(options['nEpochs']):

    for data_train in trainLoader:
        total_batch_n += 1
        data_test = next(iter(testLoader))
        update_batch_history(data_train, data_test)
        if total_batch_n % options['calculate_loss_per_n_batches'] == 0:
            print_stats(BATCH)
            saved_batch_n += 1

    # end of epoch
    for tool in range(len(tools)):
        if (tools[tool] != None):
            for stat in range(2):
                for split in [TRAIN, TEST]:
                    history[stat][tool][split][EPOCH].append(history[stat][tool][split][BATCH][-1])
    print_stats(EPOCH)

    # save results
    if options['saveFinalModel'] and (options['saveModelEveryNEpochs'] > 0) and ((epoch+1) % options['saveModelEveryNEpochs'] == 0):
        if not os.path.exists(options['outPath']): os.makedirs(options['outPath'])
        for tool in range(len(tools)):
            if (tools[tool] != None): torch.save(tools[tool].net, options['outPath']+"saved_"+tool_name[tool]+"_epoch_"+str(epoch)+".pt")
    # if end_training: break

print('-------------------------------')
print('Finished Training')

################
# Save results #
################

out_file = h5.File(options['outPath']+"training_results.h5", 'w')
for stat in [LOSS, ACCURACY, SIGNAL_ACCURACY, BACKGROUND_ACCURACY]:
    for tool in [CLASSIFICATION, REGRESSION, _GAN]:
        for split in [TRAIN, VALIDATION, TEST]:
            for timescale in [BATCH, EPOCH]:
                out_file.create_dataset(stat_name[stat]+"_"+tool_name[tool]+"_"+split_name[split]+"_"+timescale_name[timescale], data=np.array(history[stat][tool][split][timescale]))
if options['saveFinalModel']:
    for tool in range(len(tools)):
        if (tools[tool] != None): torch.save(tools[tool].net, options['outPath']+"saved_"+tool_name[tool]+".pt")

##########################
# Analyze and make plots #
##########################

print('Performing Analysis')
analyzer.analyze([tools[0], tools[1], tools[2]], validationLoader, out_file)
