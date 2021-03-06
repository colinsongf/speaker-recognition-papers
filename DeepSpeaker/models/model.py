import sys
sys.path.append("..")

import tensorflow as tf
import numpy as np
import models.DataManage as DataManage
from scipy.spatial.distance import cosine
import config

class Model(object):
    def __init__(self):
        assert len(config.OUT_CHANNEL) == config.N_RES_BLOCKS, """
        assert len(config.OUT_CHANNEL) == config.N_RES_BLOCKS,
        OUT_CHANNEL is the array represents number of out channel of each residual block. 
        So the length of OUT_CHANNEL must equal to the N_RES_BLOCKS 
        """

        self.n_speaker = config.N_SPEAKER
        self.embeddings = []
        self.n_blocks = config.N_RES_BLOCKS
        self.max_step = config.MAX_STEP
        self.n_gpu = config.N_GPU
        self.conv_weight_decay = config.CONV_WEIGHT_DECAY
        self.fc_weight_dacay = config.FC_WEIGHT_DECAY
        self.bn_epsilon = config.BN_EPSILON
        self.out_channel = config.OUT_CHANNEL
        self.learning_rate = config.LEARNING_RATE
        self.batch_size = config.BATCH_SIZE
        self.build_graph()
        
    def build_graph(self):
        
        self.create_input()
        
        inp = self.batch_frames
        
        targets = self.batch_targets
        
        for i in range(self.n_blocks):
            if i > 0:
                inp = self.residual_block(inp,
                self.out_channel[i], "residual_block_%d"%i,
                is_first_layer=True)
        
            else:     
                inp = self.residual_block(inp,
                self.out_channel[i], "residual_block_%d"%i,
                is_first_layer=False)
        
        inp = tf.nn.avg_pool(inp, ksize=[1, 2, 2, 1], 
                             stride=[1, 1, 1, 1], padding='SAME')
        
        weight_affine = self.new_variable("affine_weight", [inp.get_shape[-1], 512],
                                          weight_type="FC")
        
        bias_affine = self.new_variable("affine_bias", [512], "FC")

        inp = tf.nn.relu(tf.matmul(inp, weight_affine) + bias_affine)

        output = self.batch_normalization(inp)

        self._vector = output

        self._loss = self.triplet_loss(output, targets)
    
    @property
    def loss(self):
        return self._loss

    @property
    def vector(self):
        return self._vector

    def create_input(self):
        self.batch_frames = tf.constant([None, 400, 400, 1])
        self.batch_targets = tf.constant([None, self.n_speaker])

    def sess_init(self):
        return

    def residual_block(self, inp, out_channel, name, is_first_layer=0):
        inp_channel = inp.get_shape().as_list()[-1]
        if inp_channel*2 == out_channel:
            increased = True
            stride = 2
        else:
            increased = False
            stride = 1
        if is_first_layer:
            weight = self.new_variable(name=name+"conv", shape=[3, 3, inp_channel, out_channel],
                                       weight_type="Conv")
            conv1 = tf.nn.conv2d(inp, weight, strides=[1, 1, 1, 1], padding='SAME')
        else:
            conv1 = self.relu_conv_layer(inp, [3, 3, inp_channel, out_channel], name=name+"conv1",
                                         stride=stride, padding='SAME', bn_after_conv=False)
        conv2 = self.relu_conv_layer(conv1, [3, 3, out_channel, out_channel], name+"conv2",
                                     stride, 'SAME', bn_after_conv=False)
        if increased:
            pool_inp = tf.nn.avg_pool(inp, ksize=[1, 2, 2, 1],
                                      strides=[1, 2, 2, 1], padding='VALID')
            padded_inp = tf.pad(pool_inp, [[0, 0], [0, 0], [0, 0], [inp_channel//2, inp_channel//2]])
        else:
            padded_inp = inp
        return conv2 + padded_inp

    def triplet_loss(self, inp, targets):
        loss = tf.contrib.losses.metric_learning.triplet_semihard_loss(targets, inp, 1.0)
        return loss

    def batch_normalization(self, inp):
        dims = inp.get_shape()[-1]
        mean, variance = tf.nn.moments(inp, axes=[0, 1, 2])
        beta = tf.get_variable('beta', dims, tf.float32,
                               initializer=tf.constant(0.0, tf.float32))
        gamma = tf.get_variable('gamma', dims, tf.float32,
                                initializer=tf.constant(1.0, tf.float32))
        bn_layer = tf.nn.batch_normalization(inp, mean, variance, beta, gamma, self.bn_epsilon)
        return bn_layer

    def relu_fc_layer(self, inp, units, name):
        weight_shape = [inp.get_shape()[-1], units]
        bias_shape = [units]
        weight = self.new_variable(name=name+"_weight", shape=weight_shape,
                                   weight_type="FC")
        bias = self.new_variable(name=name+"_bias", shape=bias_shape,
                                 weight_type="Conv")
        return tf.nn.relu(tf.matmul(inp, weight) + bias)

    def relu_conv_layer(self, inp, filter_shape, stride, padding,
                        name, bn_after_conv=False):
        weight = self.new_variable(name+"_filter", filter_shape, "Conv")
        if bn_after_conv:
            conv_layer = tf.nn.conv2d(inp, weight,
                                      strides=[1, stride, stride, 1], padding=padding)
            bn_layer = self.batch_normalization(conv_layer)
            output = tf.nn.relu(bn_layer)
            return output
        else:
            bn_layer = self.batch_normalization(inp)
            relu_layer = tf.nn.relu(bn_layer)
            conv_layer = tf.nn.conv2d(relu_layer, weight,
                                      strides=[1, stride, stride, 1], padding=padding)
            return conv_layer

    def new_variable(self, name, shape, weight_type, init=tf.contrib.layers.xavier_initializer()):
        if weight_type == "Conv":
            regularizer = tf.contrib.layers.l2_regularizer(scale=self.conv_weight_decay)
        else:
            regularizer = tf.contrib.layers.l2_regularizer(scale=self.fc_weight_dacay)
        new_var = tf.get_variable(name, shape=shape, initializer=init,
                                  regularizer=regularizer)
        return new_var

    @staticmethod
    def average_gradients(grads):  # grads:[[grad0, grad1,..], [grad0,grad1,..]..]
        averaged_grads = []
        for grads_per_var in zip(*grads):
            grads = []
            for grad in grads_per_var:
                expanded_grad = tf.expand_dims(grad, 0)
                grads.append(expanded_grad)
            grads = tf.concat(grads, 0)
            grads = tf.reduce_mean(grads, 0)
            averaged_grads.append(grads)
        return averaged_grads

    def train_step(self, train_data):
        assert type(train_data) == DataManage
        grads = []
        opt = tf.train.AdamOptimizer(self.learning_rate)
        for i in range(self.n_gpu):
            with tf.device("/gpu:%d" % i):
                frames, targets = train_data.next_batch()
                frames = tf.constant(frames, dtype=tf.float32)
                targets = tf.constant(targets, dtype=tf.float32)
                self.batch_frames = frames
                self.batch_target = targets
                gradient_all = opt.compute_gradients(self.loss)
                grads.append(gradient_all)
        with tf.device("/cpu:0"):
            ave_grads = self.average_gradients(grads)
            train_op = opt.apply_gradients(ave_grads)
        return train_op, tf.reduce_sum(grads)

    def run(self,
            train_frames, 
            train_targets,
            enroll_frames,
            enroll_label,
            test_frames,
            test_label, 
            batch_size, 
            max_step, 
            save_path, 
            n_gpu):
        
        with tf.Graph().as_default():
            with tf.Session(config=tf.ConfigProto(
                    allow_soft_placement=False,
                    log_device_placement=False,
            )) as sess:
                train_data = DataManage.DataManage(train_frames, train_targets, self.batch_size)
                initial = tf.global_variables_initializer()
                sess.run(initial)
                saver = tf.train.Saver()
                for i in range(self.max_step):
                    _, loss = sess.run(self.train_step(train_data))
                    print(i, " loss:", loss)
                    if i % 25 == 0 or i + 1 == self.max_step:
                        saver.save(sess, save_path)

                self.batch_frames = enroll_frames

                embeddings = sess.run(self.vector)

                self.vector_dict = dict()
                for i in range(len(enroll_label)):
                    if self.vector_dict[np.argmax(enroll_label[i])]:
                        self.vector_dict[np.argmax(enroll_label[i])] = embeddings[i]
                    else:
                        self.vector_dict[np.argmax(enroll_label)[i]] += embeddings[i]
                        self.vector_dict[np.argmax(enroll_label)[i]] /= 2
                
                self.batch_frames = test_frames
                
                embeddings = sess.run(self.vector)
                support = 0
                for i in range(len(embeddings)):
                    keys = self.vector_dict.keys()
                    score = 0
                    for key in keys:
                        new_score = cosine(self.vector_dict[key], embeddings[i])
                        if new_score > score:
                            label = key
                    if label == np.argmax(test_label[i]):
                        support += 1
                with open('/media/data/result/deep_speaker_in_c863', 'w') as f:
                    s = "Acc is %f" % (support/len(embeddings))
                    f.writelines(s)


                




