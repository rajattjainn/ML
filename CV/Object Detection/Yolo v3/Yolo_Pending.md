### ToDo

#### Pending
- How to decide the size of machine ? 
- Handle the cases when there is GT Box while training
- Handle Grayscale Image
- Loss is not decreasing as of now. Look for solutions/alternatives and have learning graphs for the metrics
    - mAP
- Get away from 416, have a global variable
- Write function to download datasets and split them in test/val folders
- Write script to set up everything automatically
    - download yolo weights
    - set up conda
- Specify the path of images in a config file
- Train the network with a different set of classes 
- Check #TODO blocks
- Data Augmentation

#### Done
- The train operation fails when training on 14 GB machine, Coco128 dataset. 
    - <span style="color:green">Gradient was consuming all the memory. Calculated loss at each mini-batch and called zero_grad at the start of every mini-batch iteration.</span>