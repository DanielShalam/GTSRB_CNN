import torch
from PIL import Image
from torch import nn
from utils import compute_out_size, count_acc, count_params, plot_data
import numpy as np
import matplotlib.pyplot as plt
from data.hw2_labels_dictionary import classes
# prints colors
CEND = '\33[0m'
CRED = '\33[31m'
CGREEN = '\33[32m'


def conv_block(in_channels, out_channels, k_size, activation, padding=1, batch_norm=True):
    """ convolutional block. perform according to batch_norm flag."""
    if batch_norm:
        bn = nn.BatchNorm2d(out_channels)
        nn.init.uniform_(bn.weight)
        return nn.Sequential(
            nn.Conv2d(in_channels, out_channels, kernel_size=k_size, stride=(1, 1), padding=(padding, padding)),
            bn,
            nn.MaxPool2d(2),
            activation,
            nn.Dropout2d(p=0.25)
        )
    else:
        return nn.Sequential(
            nn.Conv2d(in_channels, out_channels, kernel_size=k_size, stride=(1, 1), padding=(padding, padding)),
            nn.MaxPool2d(2),
            activation
        )


class ConvNet(nn.Module):
    """ CNN model """

    def __init__(self, fe_dims, c_dims, k_size=3, padding=1, mode='f_conv'):
        super().__init__()
        dropout = False if mode == 'f_connected' else True
        self.mode = mode
        fe_layers = []
        c_layers = []
        # compute size for fully connected classifier
        self.h, self.w = compute_out_size(num_layers=len(fe_dims), k_size=k_size, p=padding, s=1)
        self.activation = nn.LeakyReLU(negative_slope=0.1)
        # build feature extractor layers
        for in_dim, out_dim in zip(fe_dims[:-1], fe_dims[1:]):
            fe_layers += [
                conv_block(in_dim, out_dim, (k_size, k_size), activation=self.activation, padding=padding, batch_norm=dropout)
            ]

        # build classifier layers
        # if model fully-convolutional
        if self.mode == 'f_conv':
            dims = [fe_dims[-1], *c_dims]
            for idx, (in_dim, out_dim) in enumerate(zip(dims[:-1], dims[1:])):
                kernel_size = (self.h, self.w) if idx == 0 else (1, 1)
                c_layers += [
                    nn.Conv2d(in_channels=in_dim, out_channels=out_dim, kernel_size=kernel_size),
                    self.activation
                ]

        # if model fully-connected
        else:
            c_layers += [nn.Flatten()]
            dims = [fe_dims[-1] * self.h * self.w, *c_dims]
            for idx, (in_dim, out_dim) in enumerate(zip(dims[:-1], dims[1:])):
                c_layers += [
                    nn.Linear(in_dim, out_dim),
                    self.activation
                ]

        self.feature_extractor = nn.Sequential(*fe_layers)
        self.classifier = nn.Sequential(*c_layers[:-1])

    def forward(self, x):
        # feature extractor
        features = self.feature_extractor(x)
        # classifier
        class_scores = self.classifier(features)
        # class_scores = self.log_softmax(class_scores)
        return class_scores


def init_weights(m):
    if type(m) == nn.Linear:
        # find number of features
        n = m.in_features
        y = 2.0 / np.sqrt(n)
        m.weight.data.xavier_normal_()
        if m.bias is not None:
            torch.nn.init.zeros_(m.bias)

    if type(m) == nn.Conv2d:
        n = len(m.weight)
        y = 1.0 / np.sqrt(n)
        m.weight.data.uniform_(-y, y)
        if m.bias is not None:
            torch.nn.init.zeros_(m.bias)


def eval_test(model, data, device, mode, plot_errors=False):
    """ test set evaluation """
    n_correct = 0
    n_total = 0
    # evaluation loop
    model.eval()
    for i, (batch, labels, paths) in enumerate(data):
        labels = labels.to(device)
        batch = batch.to(device)
        # calc net output
        y_hat = model(batch)
        if mode == 'f_conv':
            y_hat = torch.squeeze(y_hat)
        predictions = torch.argmax(y_hat, dim=1)

        if plot_errors:
            for t in range(len(predictions)):
                if predictions[t] != labels[t]:
                    img = Image.open(paths[t])
                    plt.imshow(img)
                    real = classes[int(labels[t].cpu().detach())+1]
                    p = classes[int(predictions[t].cpu().detach())+1]
                    title = f"Real: {real}, Predicted: {p}"
                    plt.title(title)
                    plt.show()

        n_correct += torch.sum(predictions == labels).type(torch.float32)
        n_total += batch.shape[0]

    acc = (n_correct / n_total).item()
    return acc


def train_loop(model, optimizer, loss_fn, data, device, epoch, train=True, mode='f_conv'):
    """ main loop, for train or validation set """

    # decide train of validate
    if train:
        model.train()
    else:
        model.eval()

    n_total = 0
    epoch_acc = 0
    losses = torch.zeros(len(data))
    # train/validation loop
    for i, (batch, labels, _) in enumerate(data):
        optimizer.zero_grad()
        # convert to cuda
        labels = labels.to(device)
        batch = batch.to(device)
        # calc net output
        y_hat = model.forward(batch)
        if mode == 'f_conv':
            y_hat = torch.squeeze(y_hat)
        # calc loss
        loss = loss_fn(y_hat, labels)
        # calc acc
        acc = count_acc(y_hat, labels)
        epoch_acc += torch.sum(acc).type(torch.float32)
        batch_acc = acc.mean().item()
        losses[i] = loss.item()
        n_total += batch.shape[0]

        if train:
            loss.backward()
            optimizer.step()
            print('epoch {}, train {}/{}, loss={:.4f} acc={:.4f}'.format(epoch, i, len(data), loss.item(), batch_acc))

        else:
            print('epoch {}, validation {}/{}, loss={:.4f} acc={:.4f}'.format(epoch, i, len(data), loss.item(),
                                                                              batch_acc))
    epoch_acc = (epoch_acc / n_total).item()
    epoch_loss = torch.mean(losses)
    return epoch_acc, epoch_loss


def train_model(data, device, mode='f_conv'):
    """ main function, train, validate, test """

    train_set, val_set, test_set = data
    all_train_acc = []
    all_val_acc = []
    all_train_losses = []
    all_val_losses = []

    # define model params
    fe_dims = [3, 64, 64, 128]
    c_dims = [120, 80, 43]
    cross_entropy_loss = torch.nn.CrossEntropyLoss()
    max_epochs = 50
    learning_rate = 0.0005
    step_size = 15
    model = ConvNet(fe_dims=fe_dims, c_dims=c_dims, mode=mode).to(device)
    print(f"Number of params: {count_params(model)}")
    # model.apply(init_weights)    # initialize model weights
    print(model)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    scheduler = None
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size, gamma=0.1, last_epoch=-1, verbose=False)
    # early stopping params
    best_val_loss = np.inf
    j_patience = 0
    patience = 10
    early_stop = False

    # train loop
    for epoch in range(max_epochs):
        # train
        train_acc, train_loss = train_loop(model=model, optimizer=optimizer, loss_fn=cross_entropy_loss, data=train_set,
                                           device=device, epoch=epoch, train=True, mode=mode)
        all_train_acc.append(train_acc)
        all_train_losses.append(train_loss)

        # validation
        val_acc, val_loss = train_loop(model=model, optimizer=optimizer, loss_fn=cross_entropy_loss, data=val_set,
                                       device=device, epoch=epoch, train=False, mode=mode)

        all_val_acc.append(val_acc)
        all_val_losses.append(val_loss)

        print("{}   epoch {} | train loss: {}| train accuracy: {} {}".format(CRED, epoch, train_loss, train_acc, CEND))
        print("{}   epoch {} | validation loss: {}| validation accuracy: {} {}".format(CRED, epoch, val_loss, val_acc,
                                                                                       CEND))
        if scheduler is not None:
            scheduler.step()

        # early stopping
        # check for improvement in the validation loss
        if val_loss < best_val_loss:
            # update algorithm parameters
            print(f"{CGREEN}Reached best loss of: {val_loss}{CEND}")
            best_epoch = epoch
            j_patience = 0
            best_val_loss = val_loss
            torch.save(model.state_dict(), f"models/best_model_{mode}.pt")
        else:
            j_patience += 1

        # if the model not improve for 'patience' iterations
        if j_patience >= patience:
            model.load_state_dict(torch.load(f"models/best_model_{mode}.pt"))
            early_stop = True
            break

        print(eval_test(model, test_set, device, mode))

    if not early_stop: best_epoch = max_epochs
    test_acc = eval_test(model, test_set, device, mode)
    plot_data(all_train_acc, all_val_acc, all_train_losses, all_val_losses, best_epoch=best_epoch)
    print(f"{CGREEN}    Test set accuracy: {test_acc} {CEND}")
