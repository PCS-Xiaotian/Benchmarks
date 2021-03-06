# coding: utf-8
import os
import sys
import time

import numpy

import theano
import theano.tensor as T
from theano.tensor.shared_randomstreams import RandomStreams

from utils import load_data

from code.logistic_sgd import LogisticRegression 
from code.mlp import HiddenLayer
from code.rbm import RBM
from code.DBN import DBN
import pandas as pd

def build_finetune_functions(self, datasets, batch_size, learning_rate):
    (train_set_x, train_set_y) = datasets[0]
    (test_set_x, test_set_y) = datasets[1]

    # compute number of minibatches for training, validation and testing
    n_test_batches = test_set_x.get_value(borrow=True).shape[0]
    n_test_batches /= batch_size

    index = T.lscalar('index')  # index to a [mini]batch

    # compute the gradients with respect to the model parameters
    gparams = T.grad(self.finetune_cost, self.params)

    # compute list of fine-tuning updates
    updates = []
    for param, gparam in zip(self.params, gparams):
        updates.append((param, param - gparam * learning_rate))

    train_fn = theano.function(
        inputs=[index],
        outputs=self.finetune_cost,
        updates=updates,
        givens={
            self.x: train_set_x[
                index * batch_size: (index + 1) * batch_size
            ],
            self.y: train_set_y[
                index * batch_size: (index + 1) * batch_size
            ]
        }
    )

    test_score_i = theano.function(
        [index],
        self.errors,
        givens={
            self.x: test_set_x[
                index * batch_size: (index + 1) * batch_size
            ],
            self.y: test_set_y[
                index * batch_size: (index + 1) * batch_size
            ]
        }
    )

    # Create a function that scans the entire test set
    def test_score():
        return [test_score_i(i) for i in xrange(n_test_batches)]

    return train_fn, test_score

def test_DBN(finetune_lr=0.1, pretraining_epochs=0,
             pretrain_lr=0.01, k=1, training_epochs=10,
             dataset='mnist.pkl.gz', batch_size=10, hidden_layers_sizes=[1000,1000,1000]):
    """
    Demonstrates how to train and test a Deep Belief Network.

    This is demonstrated on MNIST.

    :type finetune_lr: float
    :param finetune_lr: learning rate used in the finetune stage
    :type pretraining_epochs: int
    :param pretraining_epochs: number of epoch to do pretraining
    :type pretrain_lr: float
    :param pretrain_lr: learning rate to be used during pre-training
    :type k: int
    :param k: number of Gibbs steps in CD/PCD
    :type training_epochs: int
    :param training_epochs: maximal number of iterations ot run the optimizer
    :type dataset: string
    :param dataset: path the the pickled dataset
    :type batch_size: int
    :param batch_size: the size of a minibatch
    """

    datasets = load_data(dataset)

    train_set_x, train_set_y = datasets[0]
    test_set_x, test_set_y = datasets[1]

    n_in = train_set_x.shape[1].eval()
    n_out = len(set(train_set_y.eval()))

    # compute number of minibatches for training and testing
    n_train_batches = train_set_x.get_value(borrow=True).shape[0] / batch_size

    # numpy random generator
    numpy_rng = numpy.random.RandomState(123)
    print '... building the model'
    # construct the Deep Belief Network
    dbn = DBN(numpy_rng=numpy_rng, n_ins=n_in,
              hidden_layers_sizes=hidden_layers_sizes,
              n_outs=n_out)

    # start-snippet-2
    #########################
    # PRETRAINING THE MODEL #
    #########################
    print '... getting the pretraining functions'
    pretraining_fns = dbn.pretraining_functions(train_set_x=train_set_x,
                                                batch_size=batch_size,
                                                k=k)

    print '... pre-training the model'
    start_time = time.clock()
    ## Pre-train layer-wise
    TIME = time.time()
    for i in xrange(dbn.n_layers):
        # go through pretraining epochs
        for epoch in xrange(pretraining_epochs):
            # go through the training set
            c = []
            for batch_index in xrange(n_train_batches):
                c.append(pretraining_fns[i](index=batch_index,
                                            lr=pretrain_lr))
            print 'Pre-training layer %i, epoch %d, cost ' % (i, epoch),
            #print numpy.mean(c), time.time()-TIME
            #print numpy.mean(c), numpy.max(c), numpy.min(c), len(c), ' time: %.2f' % (time.time()-TIME)
            print numpy.mean(c)
            print 'Stat Layers:%d LayerSize:%d BatchSize:%d PreTrainingLayer:%d Time:%.2f' % (len(hidden_layers_sizes),hidden_layers_sizes[0],batch_size,i,time.time()-TIME)
            TIME = time.time()

    end_time = time.clock()
    # end-snippet-2
    print >> sys.stderr, ('The pretraining code for file ' +
                          os.path.split(__file__)[1] +
                          ' ran for %.2fm' % ((end_time - start_time) / 60.))
    ########################
    # FINETUNING THE MODEL #
    ########################

    # get the training and testing function for the model
    print '... getting the finetuning functions'
    train_fn, test_model = build_finetune_functions(dbn,
        datasets=datasets,
        batch_size=batch_size,
        learning_rate=finetune_lr
    )

    print '... finetuning the model'
    # early-stopping parameters
    #patience = 4 * n_train_batches  # look as this many examples regardless
    patience = 5000  # look as this many examples regardless
    patience_increase = 2.    # wait this much longer when a new best is
                              # found
    improvement_threshold = 0.995  # a relative improvement of this much is
                                   # considered significant
    test_frequency = min(n_train_batches, patience / 2)
                                  # go through this many
                                  # minibatches before checking the network
                                  # on the test set; in this case we
                                  # check every epoch

    # Jason changed, pcs, make the test_freq higher is good for performance, especially when the dataset is large.
    test_frequency = n_train_batches

    best_test_score = numpy.inf
    test_score = 0.
    start_time = time.clock()

    done_looping = False
    epoch = 0
    score = []
    TIME = time.time()
    batch_range =  numpy.arange(n_train_batches)
    while (epoch < training_epochs) and (not done_looping):
        epoch = epoch + 1
        numpy.random.shuffle(batch_range)
        for minibatch_index in xrange(n_train_batches):
        #for minibatch_index in batch_range:
            minibatch_avg_cost = train_fn(batch_range[minibatch_index])
            iter = (epoch - 1) * n_train_batches + minibatch_index

            if (iter + 1) % test_frequency == 0:

                test_losses = test_model()
                this_test_score = numpy.mean(test_losses)
                score.append([epoch,this_test_score])
                print(
                    'epoch %i, minibatch %i/%i, test error %f %%'
                    % (
                        epoch,
                        minibatch_index + 1,
                        n_train_batches,
                        this_test_score * 100.
                    )
                )

                # print 'Stat Layers:%d LayerSize:%d PreTrainingLayer:%d Time: %.2f' % (len(hidden_layers_sizes),hidden_layers_sizes[0],3,time.time()-TIME)
                i+=1
                print 'Stat Layers:%d LayerSize:%d BatchSize:%d PreTrainingLayer:%d Time:%.2f' % (len(hidden_layers_sizes),hidden_layers_sizes[0],batch_size,i,time.time()-TIME)
                TIME = time.time()

                # if we got the best test score until now
                if this_test_score < best_test_score:

                    #improve patience if loss improvement is good enough
                    if (
                        this_test_score < best_test_score *
                        improvement_threshold
                    ):
                        patience = max(patience, iter * patience_increase)

                    # save best test score and iteration number
                    best_test_score = this_test_score
                    best_iter = iter

            if patience <= iter:
                pass

    df = pd.DataFrame(score)
    spec = '%dx%d' % (hidden_layers_sizes[0], len(hidden_layers_sizes))
    df.to_pickle('result/%s_%s_DBN.log' % (os.path.basename(dataset), spec))

    end_time = time.clock()
    print(
        (
            'Optimization complete with best test performance %f %% obtained at iteration %i'
        ) % (best_test_score * 100., best_iter + 1)
    )
    print >> sys.stderr, ('The fine tuning code for file ' +
                          os.path.split(__file__)[1] +
                          ' ran for %.2fm' % ((end_time - start_time)
                                              / 60.))


if __name__ == '__main__':
    if len(sys.argv) > 3:
        dataset = sys.argv[1]
        n_units = int(sys.argv[2])
        n_layers = int(sys.argv[3])
        hidden_layers_sizes = [n_units] * n_layers
        batch_size = 10
        try:
            batch_size = int(sys.argv[4])
        except:
            pass	
        #spec = '%dx%d' % (hidden_layers_sizes[0], len(hidden_layers_sizes))
        spec = '%dx%d %d ' % (hidden_layers_sizes[0], len(hidden_layers_sizes), batch_size)
        print spec
        test_DBN(dataset=dataset, hidden_layers_sizes=hidden_layers_sizes, batch_size=batch_size)
    else:
        sys.exit('DBN.py filename n_units n_layers')
