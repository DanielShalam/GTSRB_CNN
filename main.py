import gtsrb_dataset as dataset
from torch.utils.data import DataLoader
from torch.utils.data.sampler import SubsetRandomSampler
import torch
import numpy as np
import model
from utils import data_transform, data_translate, data_shear
import pandas as pd


def eval_net(data):
    fe_dims = [3, 64, 64, 128]
    c_dims = [120, 80, 43]
    trained_model = model.ConvNet(fe_dims=fe_dims, c_dims=c_dims, mode='f_conv').to(device)
    trained_model.load_state_dict(torch.load("final_models/best_model_f_conv.pt", map_location=device))
    acc = model.eval_test(trained_model, data, device, 'f_conv')
    print(f"Test set average accuracy: {acc}")


if __name__ == '__main__':
    """ insert 0 to test fully-convolutional model, 1 to train it. """
    to_train = int(input("Test fully-convolutional model: 0, Train: 1. "))
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    validation_split = 0.2
    mode = ['f_connected', 'ef_connected_b_d', 'f_conv']
    # build iterator for train and test set
    train_set = dataset.CostumeGTSRB(root_dir='data', csv_path='Train.csv', transform=data_transform)

    test_set = dataset.CostumeGTSRB(root_dir='data', csv_path='Test.csv', transform=data_transform)

    # train validation split
    # Creating data indices for training and validation splits:
    dataset_size = len(train_set)
    indices = np.arange(dataset_size)
    split = int(np.floor(validation_split * dataset_size))
    # shuffle data
    np.random.seed(42)
    np.random.shuffle(indices)

    train_indices, val_indices = indices[split:], indices[:split]

    # create new train set with data augmentation
    new_train_csv = pd.read_csv('data/Train.csv')
    new_train_csv = new_train_csv.set_index(pd.Index(indices))
    new_train_csv = new_train_csv.iloc[train_indices]

    # create sheared dataset
    new_indices = np.arange(dataset_size, dataset_size + len(train_indices))
    new_train_csv = new_train_csv.set_index(pd.Index(new_indices))
    train_set_shear = dataset.CostumeGTSRB(root_dir='data', csv_path='Train.csv', transform=data_shear,
                                           csv_file=new_train_csv)

    # concat train set with augmented train sets
    new_train_indices = np.concatenate([train_indices, new_indices])
    full_train_set = torch.utils.data.ConcatDataset([train_set, train_set_shear])

    # Creating PT data samplers and loaders:
    train_sampler = SubsetRandomSampler(new_train_indices)
    val_sampler = SubsetRandomSampler(val_indices)

    # Data loaders
    train_loader = DataLoader(full_train_set, batch_size=64, num_workers=4, sampler=train_sampler)
    val_loader = DataLoader(train_set, batch_size=64, num_workers=4, sampler=val_sampler)
    test_loader = DataLoader(test_set, batch_size=64, shuffle=False, num_workers=4)

    if to_train:
        # # train model according to mode
        current_model = model.train_model([train_loader, val_loader, test_loader], device, mode=mode[1])

        fe_dims = [3, 64, 64, 128]
        c_dims = [120, 80, 43]
        current_model = model.ConvNet(fe_dims=fe_dims, c_dims=c_dims, mode=mode[1]).to(device)
        current_model.load_state_dict(torch.load(f"models/best_model_{mode[1]}.pt", map_location=device))
        acc = model.eval_test(current_model, data=test_loader, device=device, mode=mode[1])
        print(acc)

    else:
        eval_net(test_loader)
