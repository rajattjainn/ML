import os

import matplotlib.pyplot as plt
import numpy as np
from torch.utils.data import DataLoader
import torch
import torch.nn as nn
import torchvision.transforms as transforms

from torchinfo import summary

from image_utils import DogsCats
from simple_cnn import SimpleCNN

import logging 


curr_dir = os.path.dirname(os.path.realpath(__file__))
train_data_path = os.path.join(curr_dir, "Data")

logging.basicConfig(filename="std.log", 
					format='%(asctime)s %(message)s', 
					filemode='w') 

#Let us Create an object 
logger=logging.getLogger() 

#Now we are going to Set the threshold of logger to DEBUG 
logger.setLevel(logging.DEBUG) 

"""
The resize dimensions 768x1050 has been arrived at by iterating
over all the input images (corresponding to both test and train
data) and finding the maximum dimensions of an image."""

input_transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Resize([768, 1050])
])

train_data = DogsCats(train_data_path, input_transform)
train_loader = DataLoader(train_data, shuffle=True, batch_size=64)


def train_model(neural_net, train_loader, lr, momentum, 
            optimiser_type, loss_fn):
    optimiser = optimiser_type(neural_net.parameters(), 
                lr=lr, momentum = momentum)
    for batch, (pixels, labels) in enumerate(train_loader):
        summary(neural_net, pixels.size())
        
        y_preds = neural_net(pixels)
        loss = loss_fn(y_preds, labels)
        optimiser.zero_grad()
        loss.backward()
        optimiser.step()
        print (f"batch: {batch}, loss = {loss.item()}")
        logger.debug("batch: " + str(batch) + ", loss = " + str(loss.item()))


def train_simple_cnn():
    simple_cnn = SimpleCNN()
    learning_rate = 1e-3
    loss_fn = nn.CrossEntropyLoss()
    sgd_optimiser = torch.optim.SGD
    momentum = 0.9
    train_model(simple_cnn, train_loader, learning_rate, momentum, 
            sgd_optimiser, loss_fn)


train_simple_cnn()