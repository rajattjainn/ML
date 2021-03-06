import numpy as np
import torch
from torch import nn as nn
import torchvision.ops as tvo

import utils


class EmptyLayer(nn.Module):
    def __init__(self) -> None:
        super().__init__()

def create_module_list(layer_dic_list):
    """
    Read the dictionary containing information of various layers and convert the dic into 
    a Module List, each item being a module in the neural network. 
    @param layer_dic_list: dictionary of layers
    @returns net_info: network's meta information
    @returns module_list: the module list 
    """
    # ModuleList is being used to enable transfer learning we might want to work on later.
    module_list = nn.ModuleList()
    net_info = layer_dic_list[0]
    layer_dic_list = layer_dic_list[1:]

    prev_filter = 3
    filter_list = []

    for index, layer in enumerate(layer_dic_list):
        module = nn.Sequential()
        if layer[utils.LAYER_TYPE] == "convolutional":
            out_filters = int(layer["filters"])
            kernel = int(layer["size"])
            stride = int(layer["stride"])
            pad = int(layer["pad"])
            activation = layer["activation"]

            #using the value of padding as defined: https://github.com/AlexeyAB/darknet/wiki/CFG-Parameters-in-the-different-layers
            if pad:
                padding = kernel // 2
            else:
                padding = 0
            
            try:
                batch_normalize = layer["batch_normalize"]
                bias = False
            except:
                bias = True
                batch_normalize = 0
            
            conv_module = nn.Conv2d(prev_filter, out_filters, kernel, stride = stride, padding = padding, bias = bias)
            module.add_module("conv_{0}".format(index), conv_module)

            if batch_normalize:
                batch_norm_module = nn.BatchNorm2d(out_filters)
                module.add_module("batchnorm_{0}".format(index), batch_norm_module)
            
            if activation == "leaky":
                activation_module = nn.LeakyReLU(0.1)
                module.add_module("leaky_{0}".format(index), activation_module)

        if layer[utils.LAYER_TYPE] == "shortcut":
            shortcut_module = EmptyLayer()
            module.add_module("shortcut_{0}".format(index), shortcut_module)

        if layer[utils.LAYER_TYPE] == "upsample":
            stride = layer["stride"]
            upsample_module = nn.Upsample(scale_factor = stride, mode="bilinear")
            module.add_module("upsample_{0}".format(index), upsample_module)

        if layer[utils.LAYER_TYPE] == "route":
            route_module = EmptyLayer()
            module.add_module("route_{0}".format(index), route_module)
            prev_layers = layer["layers"]
            if "," in prev_layers:
                prev_layers = prev_layers.split(",")
                prev_layer1 = int(prev_layers[0])
                prev_layer2 = int(prev_layers[1])

                if prev_layer1 < 0:
                    prev_layer1 = index + prev_layer1
                if prev_layer2 < 0:
                    prev_layer2 = index + prev_layer2

                filter1 = filter_list[prev_layer1]
                filter2 = filter_list[prev_layer2]
                out_filters = filter1 + filter2
            else:
                prev_layers = int(prev_layers)
                out_filters = filter_list[prev_layers]

        if layer[utils.LAYER_TYPE] == "yolo":
            yolo_module = EmptyLayer()
            module.add_module("yolo_{0}".format(index), yolo_module)

        module_list.append(module)
        prev_filter = out_filters
        filter_list.append(prev_filter)

    
    return net_info, module_list

def perform_math_on_yolo_output(input, anchors, height):
    """
    This function performs the various mathematical operations to be performed on the output of 
    a yolo layer as defined in Yolov3 paper defines. These operations help in getting the correct 
    value for coordinates, objectness score, and class confidence scores.
    
    The operations are performing sigmoid function on x and y coordinates and adjusting the coordinates
    to their correct position in the output grid; sigmoid on objectness score; and sigmoid on class 
    confidence scores. Also, multiply the anchor width and height to natural exponent of tw and th 
    values recieved from the network output.
    
    """
    input = input.float()
    batch_size = input.size(0)
    grid_size = input.size(2)
    stride = height // input.size(3)

    anc_tensor = torch.tensor(anchors)
    anc_tensor = anc_tensor.repeat(grid_size*grid_size,1)
    anc_tensor = anc_tensor/stride
    
    input = input.view(batch_size, -1, grid_size * grid_size)
    input = input.transpose(1,2).contiguous()
    input = input.view(batch_size, grid_size * grid_size * 3, -1)

    # perform yolo calculations
    input[:, :, 0] = torch.sigmoid(input[:, :, 0])
    input[:, :, 1] = torch.sigmoid(input[:, :, 1])
    input[:, :, 4] = torch.sigmoid(input[:, :, 4])
    input[:, :, 5:] = torch.sigmoid(input[:, :, 5:]) 
    input[:, :,2] = anc_tensor[:,0] * torch.exp(input[:, :, 2])
    input[:, :,3] = anc_tensor[:,1] * torch.exp(input[:, :, 3])

    x_cord_tensor, y_cord_tensor = utils.get_mesh_grid(grid_size)
    
    input[:, :, 0] = input[:, :, 0] + x_cord_tensor.squeeze(1)
    input[:, :, 1] = input[:, :, 1] + y_cord_tensor.squeeze(1)
    # multiply the coordinates by stride 
    input[:, :, :4] = input[:, :, :4] * stride
    
    return input

class Yolo3(nn.Module):
    def __init__(self, cfg_file):
        super().__init__()
        self.layer_dic_list = utils.parse_cfg(cfg_file)
        self.net_info, self.module_list = create_module_list(self.layer_dic_list)


    def forward(self, input):
        # net_info layer not required 
        layer_dic_list = self.layer_dic_list[1:]
        module_list = self.module_list
        
        # a list to hold various feature maps. 
        # This will be required during route and shortcut layer when we'll 
        # need to retrieve and concatenate feature maps from previous layers.
        feature_map_list = []

        # Flag to tell us if we have an output from the yolo layer or not.
        dtctn_exists = False
        
        for index, layer_dic in enumerate(layer_dic_list):
            if layer_dic[utils.LAYER_TYPE] == "convolutional":
                output = module_list[index](input)

            elif layer_dic[utils.LAYER_TYPE] == "shortcut":
                from_layer = int(layer_dic["from"])
                abs_shrtct_layer = index + from_layer
                output = feature_map_list[index - 1] + feature_map_list[abs_shrtct_layer]

            elif layer_dic[utils.LAYER_TYPE] == "upsample":
                output = module_list[index](input)

            elif layer_dic[utils.LAYER_TYPE] == "route":
                layers = layer_dic["layers"]
                
                # if the output is route layer depends on two layers 
                if "," in layers:
                    layers = layers.split(",")
                    layer1 = int(layers[0])
                    layer2 = int(layers[1])

                    if layer1 < 0:
                        layer1 = index + layer1
                    if layer2 < 0:
                        layer2 = index + layer2

                    out1 = feature_map_list[layer1]
                    out2 = feature_map_list[layer2]
                    output = torch.cat((out1, out2), 1)
                
                # if the output is route layer depends on only one layer
                else:
                    layer = int(layers)
                    absolute_route_layer = index + layer
                    output = feature_map_list[absolute_route_layer]
                    
            elif layer_dic[utils.LAYER_TYPE] == "yolo":    

                height = int(self.net_info["height"])
                anchor_str = layer_dic["anchors"].split(",")
                mask = layer_dic["mask"].split(",")

                anchors = utils.get_anchors(anchor_str, mask)
                
                output = perform_math_on_yolo_output(input, anchors, height)
                if dtctn_exists:
                    detection_tensor = torch.cat((detection_tensor, output), 1)
                else:
                    detection_tensor = output
                    dtctn_exists = True
            feature_map_list.append(output)
            input = output
        
        # TODO: Check this implementation
        detection_tensor = torch.nan_to_num(detection_tensor)
        return detection_tensor

    # The load_weights functions has been copied as it is from Ayoosh kathuria's blog.
    def load_weights(self, weightfile):
    #Open the weights file
        fp = open(weightfile, "rb")
        
        #The first 5 values are header information 
        # 1. Major version number
        # 2. Minor Version Number
        # 3. Subversion number 
        # 4,5. Images seen by the network (during training)
        header = np.fromfile(fp, dtype = np.int32, count = 5)
        self.header = torch.from_numpy(header)
        self.seen = self.header[3]   
            
        weights = np.fromfile(fp, dtype = np.float32)
            
        ptr = 0
        for i in range(len(self.module_list)):
            module_type = self.layer_dic_list[i + 1][utils.LAYER_TYPE]
        
            #If module_type is convolutional load weights
            #Otherwise ignore.
                
            if module_type == "convolutional":
                model = self.module_list[i]
                try:
                    batch_normalize = int(self.layer_dic_list[i+1]["batch_normalize"])
                except:
                    batch_normalize = 0
                
                conv = model[0]
                    
                    
                if (batch_normalize):
                    bn = model[1]
            
                    #Get the number of weights of Batch Norm Layer
                    num_bn_biases = bn.bias.numel()
            
                    #Load the weights
                    bn_biases = torch.from_numpy(weights[ptr:ptr + num_bn_biases])
                    ptr += num_bn_biases
            
                    bn_weights = torch.from_numpy(weights[ptr: ptr + num_bn_biases])
                    ptr  += num_bn_biases
            
                    bn_running_mean = torch.from_numpy(weights[ptr: ptr + num_bn_biases])
                    ptr  += num_bn_biases
            
                    bn_running_var = torch.from_numpy(weights[ptr: ptr + num_bn_biases])
                    ptr  += num_bn_biases
            
                    #Cast the loaded weights into dims of model weights. 
                    bn_biases = bn_biases.view_as(bn.bias.data)
                    bn_weights = bn_weights.view_as(bn.weight.data)
                    bn_running_mean = bn_running_mean.view_as(bn.running_mean)
                    bn_running_var = bn_running_var.view_as(bn.running_var)
            
                    #Copy the data to model
                    bn.bias.data.copy_(bn_biases)
                    bn.weight.data.copy_(bn_weights)
                    bn.running_mean.copy_(bn_running_mean)
                    bn.running_var.copy_(bn_running_var)
                    
                else:
                    #Number of biases
                    num_biases = conv.bias.numel()
                    
                    #Load the weights
                    conv_biases = torch.from_numpy(weights[ptr: ptr + num_biases])
                    ptr = ptr + num_biases
                    
                    #reshape the loaded weights according to the dims of the model weights
                    conv_biases = conv_biases.view_as(conv.bias.data)
                    
                    #Finally copy the data
                    conv.bias.data.copy_(conv_biases)
                        
                #Let us load the weights for the Convolutional layers
                num_weights = conv.weight.numel()
                    
                #Do the same as above for weights
                conv_weights = torch.from_numpy(weights[ptr:ptr+num_weights])
                ptr = ptr + num_weights
                    
                conv_weights = conv_weights.view_as(conv.weight.data)
                conv.weight.data.copy_(conv_weights)


def analyze_detections(img, cnf_thres = 0.5, iou_thres = 0.4):
    """
    Analyse all the detections given by the yolo layer. Filter out the predictions
    which are below a certain threshold (cnf_thres). Apply NMS using iou_thres.  
    """
    img = img[img[:, 4] > cnf_thres]
    
    # no detections
    if img.size()[0] == 0:
        return 0

    # convert bx, by, bw, bh into bx1, by1, bx2, by2
    boxes = img.new(img.shape)
    boxes[:,0] = img[:, 0] - img[:, 2]/2
    boxes[:,1] = img[:, 1] - img[:, 3]/2
    boxes[:,2] = img[:, 0] + img[:, 2]/2
    boxes[:,3] = img[:, 1] + img[:, 3]/2
    img[:, :4] = boxes[:,:4]
    
    # get the max class confidence and corresponding class
    max_values, class_values = torch.max(img[:,5:], 1)

    # create a tensor that has 7 elements: bx1, by1, bx2, by2, conf, class_conf, class
    img = torch.cat((img[:, :5], max_values.float().unsqueeze(1), class_values.float().unsqueeze(1)), 1)
    
    dtctn_tnsr_exsts = False
    classes = torch.unique(img[:, 6])
    for cls in classes:
        # retrieve all the rows which correspond to class cls
        cls_tensor = img[torch.where(img[:, 6] == cls)]

        # sort cls_tensor according to max confidence
        cls_tensor = cls_tensor[cls_tensor[:,5].sort(descending = True)[1]]
           
        # box_iou takes tensors which have only 4 columns
        iou_tensor = tvo.box_iou(cls_tensor[:,:4], cls_tensor[:,:4])
    
        rejected_indices = []
        detected_indices = []

        #TODO: have a helper function to generate an image with all bbs drawn at this stage
        for row in range(iou_tensor.size(0)):
            if row in rejected_indices:
                continue
            # get all the rows which have iou greater than the threshold. the row
            # itself would have an IOU of 1 
            exceeding_thres_tensor = torch.where(iou_tensor[row] > iou_thres)[0]
            
            # all the rows except the current row are discarded owing to NMS
            rejected_indices.extend(exceeding_thres_tensor.tolist())

            # the current row is added to the detected tensor list
            detected_indices.append(row)
        
        if dtctn_tnsr_exsts:
            detection_tensor = torch.cat((detection_tensor, cls_tensor[detected_indices]), 0)
                
        else:
            detection_tensor = cls_tensor[detected_indices]
            dtctn_tnsr_exsts = True
    try:
        return detection_tensor
    except:
        return 0
