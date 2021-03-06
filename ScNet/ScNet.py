#!/usr/bin/env python

"""
没有对矩阵进行求逆的DetNet,属于在作者的基础上取消求逆的基础版本
将全连接的方式改为单点连接的非全连接形式
"""
import datetime

import numpy as np
import tensorflow as tf
import time as tm

###start here
"""
Parameters
K - size of x
N - size of y
snrdb_low - the lower bound of noise db used during training
snr_high - the higher bound of noise db used during training
L - number of layers in DetNet
v_size = size of auxiliary variable at each layer
hl_size - size of hidden layer at each DetNet layer (the dimention the layers input are increased to
startingLearningRate - the initial step size of the gradient descent algorithm
decay_factor & decay_step_size - each decay_step_size steps the learning rate decay by decay_factor
train_iter - number of train iterations
train_batch_size - batch size during training phase
test_iter - number of test iterations
test_batch_size  - batch size during testing phase
LOG_LOSS - equal 1 if loss of each layer should be sumed in proportion to the layer depth, otherwise all losses have the same weight 
res_alpha- the proportion of the previuos layer output to be added to the current layers output (view ResNet article)
snrdb_low_test & snrdb_high_test & num_snr - when testing, num_snr different SNR values will be tested, uniformly spread between snrdb_low_test and snrdb_high_test 
"""

sess = tf.InteractiveSession()

# parameters
K = 40
N = 80
snrdb_low = 7.0
snrdb_high = 14.0
snr_low = 10.0 ** (snrdb_low / 10.0)
snr_high = 10.0 ** (snrdb_high / 10.0)
L = 4
hl_size = K
startingLearningRate = 0.0001
decay_factor = 0.97
decay_step_size = 1000
train_iter = 5000
train_batch_size = 5000
test_iter = 200
test_batch_size = 1000
LOG_LOSS = 1  # 是否采用LOG方式
res_alpha = 0.9
num_snr = 6
snrdb_low_test = 8.0
snrdb_high_test = 13.0
full_connect = 0
"""Data generation for train and test phases
In this example, both functions are the same.
This duplication is in order to easily allow testing cases where the test is over different distributions of data than in the training phase.
e.g. training over gaussian i.i.d. channels and testing over a specific constant channel.
currently both test and train are over i.i.d gaussian channel.
"""
nowTime = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # 现在
print("K=", K, "N=", N, "L=", L, "train_iter=", train_iter, "now=", nowTime)


def generate_data_iid_test(B, K, N, snr_low, snr_high):
    H_ = np.random.randn(B, N, K)
    W_ = np.zeros([B, K, K])
    x_ = np.sign(np.random.rand(B, K) - 0.5)
    y_ = np.zeros([B, N])
    w = np.random.randn(B, N)
    Hy_ = x_ * 0
    HH_ = np.zeros([B, K, K])
    SNR_ = np.zeros([B])
    for i in range(B):
        SNR = np.random.uniform(low=snr_low, high=snr_high)
        H = H_[i, :, :]
        tmp_snr = (H.T.dot(H)).trace() / K
        H = H / np.sqrt(tmp_snr) * np.sqrt(SNR)
        H_[i, :, :] = H
        y_[i, :] = (H.dot(x_[i, :]) + w[i, :])
        Hy_[i, :] = H.T.dot(y_[i, :])
        HH_[i, :, :] = H.T.dot(H_[i, :, :])
        SNR_[i] = SNR
    return y_, H_, Hy_, HH_, x_, SNR_


def generate_data_train(B, K, N, snr_low, snr_high):
    H_ = np.random.randn(B, N, K)
    W_ = np.zeros([B, K, K])
    x_ = np.sign(np.random.rand(B, K) - 0.5)
    y_ = np.zeros([B, N])
    w = np.random.randn(B, N)
    Hy_ = x_ * 0
    HH_ = np.zeros([B, K, K])
    SNR_ = np.zeros([B])
    for i in range(B):
        SNR = np.random.uniform(low=snr_low, high=snr_high)
        H = H_[i, :, :]
        tmp_snr = (H.T.dot(H)).trace() / K
        H = H / np.sqrt(tmp_snr) * np.sqrt(SNR)
        H_[i, :, :] = H
        y_[i, :] = (H.dot(x_[i, :]) + w[i, :])
        Hy_[i, :] = H.T.dot(y_[i, :])
        HH_[i, :, :] = H.T.dot(H_[i, :, :])
        SNR_[i] = SNR
    return y_, H_, Hy_, HH_, x_, SNR_


def piecewise_linear_soft_sign(x):
    t = tf.Variable(0.1)
    y = -1 + tf.nn.relu(x + t) / (tf.abs(t) + 0.00001) - tf.nn.relu(x - t) / (tf.abs(t) + 0.00001)
    return y


def affine_layer(x, input_size, output_size, Layer_num, limit_mat, full_connect):
    W = tf.Variable(tf.random_normal([input_size, output_size], stddev=0.01))
    if full_connect == 0:
        W = tf.multiply(W, limit_mat)
    w = tf.Variable(tf.random_normal([1, output_size], stddev=0.01))
    y = tf.matmul(x, W) + w
    return y


def relu_layer(x, input_size, output_size, Layer_num):
    y = tf.nn.relu(affine_layer(x, input_size, output_size, Layer_num))
    return y


def sign_layer(x, input_size, output_size, Layer_num, limit_mat, full_connect):
    y = piecewise_linear_soft_sign(affine_layer(x, input_size, output_size, Layer_num, limit_mat, full_connect))
    return y


# tensorflow placeholders, the input given to the model in order to train and test the network
HY = tf.placeholder(tf.float32, shape=[None, K])
X = tf.placeholder(tf.float32, shape=[None, K])
HH = tf.placeholder(tf.float32, shape=[None, K, K])

batch_size = tf.shape(HY)[0]

# give the weight of matrix
# TODO - 将全连接的方式更改为非全连接的方式
weigth_matrix = np.zeros((3 * K, K))
for i in range(0, K):
    for j in range(0, 3):
        weigth_matrix[j * K + i, i] = 1

S = []
S.append(tf.zeros([batch_size, K]))
LOSS = []  # 每一层的代价函数
LOSS.append(tf.zeros([]))
BER = []
BER.append(tf.zeros([]))

# The architecture of DetNet
for i in range(1, L):
    temp1 = tf.matmul(HH, tf.expand_dims(S[-1], 2))
    temp1 = tf.squeeze(temp1, 2)
    Z = tf.concat([HY, S[-1], temp1], 1)
    S.append(sign_layer(Z, 3 * K, hl_size, 'sign' + str(i), weigth_matrix, full_connect))
    S[i] = (1 - res_alpha) * S[i] + res_alpha * S[i - 1]
    if LOG_LOSS == 1:
        LOSS.append(np.log(i) * tf.reduce_mean(tf.reduce_mean(tf.square(X - S[-1]), 1)))
    else:
        LOSS.append(tf.reduce_mean(tf.reduce_mean(tf.square(X - S[-1]), 1)))
    BER.append(tf.reduce_mean(tf.cast(tf.not_equal(X, tf.sign(S[-1])), tf.float32)))

TOTAL_LOSS = tf.add_n(LOSS)

global_step = tf.Variable(0, trainable=False)
learning_rate = tf.train.exponential_decay(startingLearningRate, global_step, decay_step_size, decay_factor,
                                           staircase=True)
train_step = tf.train.AdamOptimizer(learning_rate).minimize(TOTAL_LOSS)
init_op = tf.global_variables_initializer()

sess.run(init_op)
# Training DetNet
for i in range(train_iter):  # num of train iter
    batch_Y, batch_H, batch_HY, batch_HH, batch_X, SNR1 = generate_data_train(train_batch_size, K, N, snr_low, snr_high)
    train_step.run(feed_dict={HY: batch_HY, HH: batch_HH, X: batch_X})
    if i % 100 == 0:
        batch_Y, batch_H, batch_HY, batch_HH, batch_X, SNR1 = generate_data_iid_test(train_batch_size, K, N, snr_low,
                                                                                     snr_high)
        results = sess.run([LOSS[L - 1], BER[L - 1]], {HY: batch_HY, HH: batch_HH, X: batch_X})
        print_string = [i] + results
        print(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "|", ' '.join('%s' % x for x in print_string))

# Testing the trained model
snrdb_list = np.linspace(snrdb_low_test, snrdb_high_test, num_snr)
snr_list = 10.0 ** (snrdb_list / 10.0)
bers = np.zeros((1, num_snr))
times = np.zeros((1, num_snr))
tmp_bers = np.zeros((1, test_iter))
tmp_times = np.zeros((1, test_iter))
for j in range(num_snr):
    print(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "|", 'snr=', snrdb_list[j])
    for jj in range(test_iter):
        batch_Y, batch_H, batch_HY, batch_HH, batch_X, SNR1 = generate_data_iid_test(test_batch_size, K, N, snr_list[j],
                                                                                     snr_list[j])
        tic = tm.time()
        tmp_bers[:, jj] = np.array(sess.run(BER[L - 1], {HY: batch_HY, HH: batch_HH, X: batch_X}))
        toc = tm.time()
        tmp_times[0][jj] = toc - tic
    bers[0][j] = np.mean(tmp_bers, 1)
    times[0][j] = np.mean(tmp_times[0]) / test_batch_size

print("now=", datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
print('snrdb_list')
print(snrdb_list)
print('bers')
print(bers)
print('times')
print(times)
