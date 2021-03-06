#-*- coding:utf-8 -*-

import tensorflow as tf
import tensorflow.contrib.slim as slim
import numpy as np
import csv
import math
import cv2
import threading
import time

start_time=time.time()

def colorization_arg_scope(weight_decay=0.00004,
                           use_batch_norm=True,
                           batch_norm_var_collection='moving_vars'):
    batch_norm_params = {
        # Decay for the moving averages.
        'decay': 0.9997,
        #  epsilon to prevent 0s in variance.
        'epsilon': 0.001,
        #  collection containing update_ops.
        'updates_collections': tf.GraphKeys.UPDATE_OPS,
        #  collection containing the moving mean and moving variance.
        'variables_collections': {
            'beta': None,
            'gamma': None,
            'moving_mean': [batch_norm_var_collection],
            'moving_variance': [batch_norm_var_collection],
        }
    }
    if use_batch_norm:
        normalizer_fn = slim.batch_norm
        normalizer_params = batch_norm_params
    else:
        normalizer_fn = None
        normalizer_params = {}
     # Set weight_decay for weights in Conv and FC layers.
    with slim.arg_scope(
            [slim.conv2d, slim.fully_connected],
            weights_regularizer=slim.l2_regularizer(weight_decay)):
        with slim.arg_scope(
                [slim.conv2d],
                weights_initializer=slim.variance_scaling_initializer(),
                activation_fn=tf.nn.relu,
                normalizer_fn=normalizer_fn,
                normalizer_params=normalizer_params) as sc:
            return sc

def enqueue(sess, data, batch_size, enqueue_op, queue_x_input, queue_y_ab, queue_y_class):
    num_data = len(data)
    data = np.array(data)
    image_size=224


    while True:
        idxs = np.arange(0, num_data)
        np.random.shuffle(idxs)
        shuf_data = data[idxs]

        for i in range(0, num_data-batch_size, batch_size):
            curr_x_input = []
            curr_y_ab = []
            curr_y_class = []

            for j in range(i, i+batch_size):
                image = cv2.imread(shuf_data[j][0])
                image = cv2.resize(image, (image_size, image_size), interpolation=cv2.INTER_AREA)
                image = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)

                input_image = image[:, :, :1]
                output_image = image[:, :, 1:]

                curr_x_input.append(input_image / 255)
                curr_y_ab.append(output_image / 255)
                curr_y_class.append(int(shuf_data[j][1]))

            curr_x_input = np.array(curr_x_input, dtype=np.float32)
            curr_y_ab = np.array(curr_y_ab,dtype=np.float32)
            curr_y_class = np.array(curr_y_class, dtype=np.float32)
            curr_y_class=np.reshape(curr_y_class,[batch_size,1])
            try:
                sess.run(enqueue_op,feed_dict={queue_x_input:curr_x_input, queue_y_ab:curr_y_ab, queue_y_class:curr_y_class})
            except:
                exit()


def Fusion(input1,input2, name):
    input2 = tf.tile(input2,[1,28*28])
    input2 = tf.reshape(input2,[batch_size,28,28,256])
    input1 = tf.concat([input1,input2],3)
    fusion = slim.conv2d(input1, 256, [3, 3], scope=name)
    return fusion

class Model:
    def __init__(self, sess):
        self.sess = sess
        self.x=np.zeros((batch_size,224,224,1))
        self.y_colorization=np.zeros((batch_size,224,224,2))
        self.y_classification=np.zeros(batch_size)
        self.build_network()

    def build_network(self):
        image_height_size = 224
        image_width_size = 224
        classification_num = 205
        loss_parameter = 1/300
        initial_learning_rate = 1e-1

        self.X = tf.placeholder(tf.float32, [batch_size,image_height_size,image_width_size,1])
        self.Y_colorization = tf.placeholder(tf.float32, [batch_size,image_height_size,image_width_size,2])
        self.Y_classification = tf.placeholder(tf.int32, [batch_size, 1])
        y_classification = tf.reshape(self.Y_classification,[-1])

        Y_classification_one_hot = tf.one_hot(y_classification, classification_num)

        with slim.arg_scope(colorization_arg_scope()):
            first_low_level = slim.stack(self.X, slim.conv2d, [(64, [3, 3], 2), (128, [3, 3], 1), (128, [3, 3], 2), (256, [3, 3], 1), (256,[3,3], 2), (512,[3,3],1)],scope='low_level')

            second_low_level1 = slim.conv2d(self.X, 64, [3, 3], stride=2, scope='low_level/low_level_1',reuse=True)
            second_low_level2 = slim.conv2d(second_low_level1, 128, [3, 3], scope='low_level/low_level_2',reuse=True)
            second_low_level3 = slim.conv2d(second_low_level2, 128, [3, 3], stride=2, scope='low_level/low_level_3',reuse=True)
            second_low_level4 = slim.conv2d(second_low_level3, 256, [3, 3], scope='low_level/low_level_4',reuse=True)
            second_low_level5 = slim.conv2d(second_low_level4, 256, [3, 3], stride=2, scope='low_level/low_level_5',reuse=True)
            second_low_level6 = slim.conv2d(second_low_level5, 512, [3, 3], scope='low_level/low_level_6', reuse=True)

            mid_level = slim.stack(first_low_level, slim.conv2d, [(512,[3,3]), (256,[3,3])], scope='mid_level')

            global_level1 = slim.stack(second_low_level6, slim.conv2d, [(512, [3, 3], 2), (512, [3, 3], 1), (512, [3, 3], 2), (512, [3, 3], 1)], scope='global_level1')
            global_level1 = slim.flatten(global_level1)
            global_level2 = slim.fully_connected(global_level1, 1024, scope='global_level2')
            global_level3 = slim.fully_connected(global_level2, 512, scope='global_level3')
            global_level4 = slim.fully_connected(global_level3, 256, scope='global_level4')

            fusion_layer = Fusion(input1=mid_level, input2=global_level4, name="fusion")

            colorization_network1 = slim.conv2d(fusion_layer,128,[3,3], scope="colorization_network1")
            colorization_network2 = tf.image.resize_images(colorization_network1, [math.ceil(image_height_size / 4), math.ceil(image_width_size / 4)])
            colorization_network3 = slim.stack(colorization_network2, slim.conv2d, [(64,[3,3]), (64,[3,3])],scope='colorization_network3')
            colorization_network4 = tf.image.resize_images(colorization_network3, [math.ceil(image_height_size / 2),math.ceil(image_width_size / 2)])
            colorization_network5 = slim.conv2d(colorization_network4, 32, [3, 3], scope="colorization_network5")

            colorization_network6 = slim.conv2d(colorization_network5, 2, [3, 3], scope="colorization_network6", activation_fn=tf.nn.sigmoid)

            self.colorization_network7 = tf.image.resize_images(colorization_network6, [image_height_size,image_width_size])

            classification_level1 = slim.fully_connected(global_level3, 256, scope='classfication_level1')
            self.classification_level2 = slim.fully_connected(classification_level1, classification_num, scope='classfication_level2')

        self.colorization_loss = tf.losses.mean_squared_error(labels=self.Y_colorization, predictions=self.colorization_network7)
        self.classification_loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(labels=Y_classification_one_hot, logits=self.classification_level2))
        self.loss = self.colorization_loss + (loss_parameter * self.classification_loss)

        update_ops = tf.get_collection_ref(tf.GraphKeys.UPDATE_OPS)
        with tf.control_dependencies(update_ops):
            global_step = tf.Variable(0, trainable=False)
            learning_rate = tf.train.exponential_decay(initial_learning_rate, global_step,100, 0.90, staircase=True)
            self.train = tf.train.AdadeltaOptimizer(learning_rate=learning_rate).minimize(self.loss)

        tf.summary.scalar('colorization_loss', self.colorization_loss)
        tf.summary.scalar('classification_loss', self.classification_loss)
        tf.summary.scalar("loss", self.loss)

        self.merged_graph = tf.summary.merge_all()

    def Loss_graph(self, X, Y_colorization, Y_classification):
        return self.sess.run(self.merged_graph, feed_dict={self.X: X, self.Y_colorization: Y_colorization, self.Y_classification: Y_classification})

    def Colorization_loss(self, X, Y_colorization, Y_classification):
        return self.sess.run(self.colorization_loss, feed_dict={self.X: X, self.Y_colorization: Y_colorization, self.Y_classification: Y_classification})

    def Classification_loss(self, X, Y_colorization, Y_classification):
        return self.sess.run(self.classification_loss, feed_dict={self.X: X, self.Y_colorization: Y_colorization, self.Y_classification: Y_classification})

    def Loss(self, X, Y_colorization, Y_classification):
        return self.sess.run(self.loss, feed_dict={self.X: X, self.Y_colorization: Y_colorization, self.Y_classification: Y_classification})

    def Train(self, X, Y_colorization, Y_classification):
        return self.sess.run(self.train,feed_dict={self.X: X, self.Y_colorization : Y_colorization, self.Y_classification : Y_classification})


#varaibles
epochs = 10 #11
batch_size = 16 #128

train_queue_capacity = batch_size*4
train_batch_capacity = train_queue_capacity//2

train_file='train_data.csv'
input_size = 224
ab_size = input_size

#initialize
csv_file = open(train_file, 'r')
csv_reader = csv.reader(csv_file)
train_data=list(csv_reader)
data_length=len(train_data)

train_queue = tf.FIFOQueue(capacity=train_queue_capacity,
                           dtypes=[tf.float32, tf.float32, tf.float32],
                           shapes=[[input_size, input_size, 1], [ab_size, ab_size, 2], [1]])

train_queue_x_input = tf.placeholder(tf.float32, shape=[None,input_size, input_size, 1])
train_queue_y_ab = tf.placeholder(tf.float32, shape=[None,ab_size, ab_size, 2])
train_queue_y_class = tf.placeholder(tf.float32, shape=[None,1])

train_enqueue_op = train_queue.enqueue_many([train_queue_x_input, train_queue_y_ab,train_queue_y_class])
train_dequeue_op = train_queue.dequeue()

train_batch_x_input, train_batch_y_ab, train_batch_y_class = tf.train.batch(train_dequeue_op, batch_size=batch_size, capacity=train_batch_capacity)

sess = tf.InteractiveSession()
model = Model(sess)
saver = tf.train.Saver()

sess.run(tf.global_variables_initializer())
#saver.restore(sess, "./ckpt/my-model-5")
writer = tf.summary.FileWriter("./board",sess.graph)

train_enqueue_thread = threading.Thread(target=enqueue,args=[sess,train_data,batch_size,train_enqueue_op,train_queue_x_input,train_queue_y_ab, train_queue_y_class])

train_enqueue_thread.isDaemon()
train_enqueue_thread.start()

coord = tf.train.Coordinator()
thread = tf.train.start_queue_runners(coord=coord, sess=sess)

#train model
cnt=0
for epoch in range(epochs):
    for i in range(0,data_length-batch_size,batch_size):
        cnt+=1
        X, Y_colorization, Y_classification = sess.run([train_batch_x_input, train_batch_y_ab, train_batch_y_class])
        model.Train(X, Y_colorization, Y_classification)

        if cnt % 100 == 0:
            print('epoch:', epoch, 'len', data_length, 'i', i, 'loss:',
                  model.Loss(X, Y_colorization, Y_classification), 'colorization_loss', model.Colorization_loss(X, Y_colorization, Y_classification), 'classificaton_loss', model.Classification_loss(X, Y_colorization, Y_classification))
            graph_loss = model.Loss_graph(X, Y_colorization, Y_classification)
            writer.add_summary(graph_loss,cnt)

    saver.save(sess, 'C:/Users/heojo/Desktop/Colorization_slim/ckpt/my-model',global_step=epoch)

end_time=time.time()
print('time',end_time-start_time)

coord.request_stop()
coord.join(thread)
writer.close()
sess.close()

#tensorboard --logdir=./board
#localhost:6006