import os
import time
import glob
import codecs
import pandas as pd

from keras.utils import to_categorical
from keras.preprocessing.sequence import pad_sequences

# TODO (John): set max_seq_len empirically.

TRAIN_FILE_EXT = 'train.*'
TEST_FILE_EXT = 'test.*'

# method naming conventions: https://stackoverflow.com/questions/8689964/why-do-some-functions-have-underscores-before-and-after-the-function-name#8689983
class Dataset(object):
    """ A class for handling data sets. """
    def __init__(self, dataset_filepath, sep='\t', names=['Word', 'Tag'],
                 header=None, max_seq_len=75):
                 self.dataset_filepath = dataset_filepath
                 self.trainset_filepath = glob.glob(os.path.join(dataset_filepath, TRAIN_FILE_EXT))[0]
                 self.testset_filepath = glob.glob(os.path.join(dataset_filepath, TEST_FILE_EXT))[0]
                 self.sep = sep
                 self.names = names
                 self.header = header
                 self.max_seq_len = max_seq_len
                 # shared by train/test
                 self.raw_dataframe = None
                 self.word_types = []
                 self.tag_types = []
                 self.word_type_count = 0
                 self.tag_type_count = 0
                 self.word_type_to_index = {}
                 self.tag_type_to_index = {}
                 # not shared by train/test
                 self.train_dataframe = None
                 self.test_dataframe = None
                 self.train_sentences = []
                 self.test_sentences = []
                 self.train_word_idx_sequence = []
                 self.test_word_idx_sequence = []
                 self.train_tag_idx_sequence = []
                 self.test_tag_idx_sequence = []

    def load_dataset(self):
        """ Coordinates loading of given data set at self.dataset_filepath.

        For a given dataset in CoNLL format at dataset_filepath, cordinates
        the loading of data into a pandas dataframe and updates instance
        attributes. Expects self.dataset_filepath to be a directory containing
        two files, train.* and test.*
        """
        start_time = time.time()
        print('Load dataset... ', end='', flush=True)

        # load the entire dataset, then grab the train and test 'frames'
        self.raw_dataframe = self._load_dataset()
        self.train_dataframe = self.raw_dataframe.loc['train']
        self.test_dataframe = self.raw_dataframe.loc['test']

        # train and test partitions share these attributes
        self.word_types, self.tag_types = self._get_types()
        self.word_type_count, self.tag_type_count = len(self.word_types), len(self.tag_types)
        self.word_type_to_index, self.tag_type_to_index = self._map_type_to_idx()

        # train/test partitions do NOT share these attributes

        ## TRAIN
        # get sentences
        self.train_sentences = self._get_sentences(self.trainset_filepath, sep=self.sep)
        # get type to idx sequences
        self.train_word_idx_sequence = self._get_type_idx_sequence(self.train_sentences)
        self.train_tag_idx_sequence = self._get_type_idx_sequence(self.train_sentences, type_='tag')
        # convert tag idx sequences to categorical
        self.train_tag_idx_sequence = self._tag_idx_sequence_to_categorical()

        ## TEST
        # get sentences
        self.test_sentences = self._get_sentences(self.testset_filepath, sep=self.sep)
        # get type to idx sequences
        self.test_word_idx_sequence = self._get_type_idx_sequence(self.test_sentences)
        self.test_tag_idx_sequence = self._get_type_idx_sequence(self.test_sentences, type_='tag')
        # convert tag idx sequences to categorical
        self.test_tag_idx_sequence = self._tag_idx_sequence_to_categorical(partition='test')

        elapsed_time = time.time() - start_time
        print('done ({0:.2f} seconds)'.format(elapsed_time))

    def _load_dataset(self):
        """ Loads data set given at self.dataset_filepath in pandas dataframe.

        Loads a given data CoNLL format at dataset_filepath into a pandas
        dataframe and updates instance. Expects self.dataset_filepath to be a
        directory containing two files, train.* and test.*

        Returns:
            single merged pandas dataframe for train and test files.
        """
        training_set = pd.read_csv(self.trainset_filepath,
                                   header=self.header, sep=self.sep,
                                   names=self.names, encoding="utf-8",
                                   # forces pandas to ignore quotes such that we
                                   # can read in '"' word type.
                                   quoting = 3,
                                   # prevents pandas from interpreting 'null' as a
                                   # NA value.
                                   na_filter=False)

        testing_set = pd.read_csv(self.testset_filepath,
                                   header=self.header, sep=self.sep,
                                   names=self.names, encoding="utf-8",
                                   quoting = 3,
                                   na_filter=False)

        # forward propogate last valid value to file NAs.
        frames = [training_set, testing_set]
        raw_dataset = pd.concat(frames, keys=['train', 'test'])
        raw_dataset = raw_dataset.fillna(method='ffill')
        return raw_dataset

    def _get_types(self):
        """ Updates attributes with word types, class types and their counts.

        Updates the attributes of a Dataset object instance with the datasets
        word types, tag types, and counts for these entities.

        Preconditions:
            assumes that the first column of the data set contains the word
            types, and the last column contains the tag types.
        """
        word_types = list(set(self.raw_dataframe.iloc[:, 0].values))
        tag_types = list(set(self.raw_dataframe.iloc[:, -1].values))
        word_types.append("ENDPAD")

        return word_types, tag_types

    def _map_type_to_idx(self):
        """ Updates attributes with type to index dictionary maps.

        Updates the attributes of a Dataset object instance with dictionaries
        mapping each word type and each tag type to a unique index.
        """
        tag_type_to_index = self._sequence_2_idx(self.tag_types)
        # pad of 1 accounts for the sequence pad (of 0) down the pipeline
        word_type_to_index = self._sequence_2_idx(self.word_types, pad=1)

        return word_type_to_index, tag_type_to_index

    def _sequence_2_idx(self, sequence, pad=0):
        """ Returns a dictionary of element:idx pairs for each element in sequence.

        Given a list, returns a dictionary of length len(sequence) + pad where
        the keys are elements of sequence and the values are unique integers.

        Args:
            sequence: a list of sequence data.
        """
        # pad accounts for idx of sequence pad
        return {e: i + pad for i, e in enumerate(sequence)}

    def _get_sentences(self, partition_filepath, sep='\t'):
        """ Returns sentences for csv/tsv file as a list lists of tuples.

        Returns a list of lists of two-tuples for the csv/tsv at
        partition_filepath, where the inner lists represent sentences, and the
        tuples are ordered pairs of (words, tags).

        Args:
            partition_filepath: filepath to csv/tsv file for train/test set partition
            sep: delimiter for csv/tsv file at filepath
        """
        master_sentence_acc = []
        indivdual_sentence_acc = []

        with codecs.open(partition_filepath, 'r', encoding='utf-8') as ds:
            for line in ds:
                if line != '\n':
                    indivdual_sentence_acc.append(tuple(line.strip().split('\t')))
                else:
                    master_sentence_acc.append(indivdual_sentence_acc)
                    indivdual_sentence_acc = []

            # in order to collect last sentence in the file
            master_sentence_acc.append(indivdual_sentence_acc)

        return master_sentence_acc

    def _get_type_idx_sequence(self, sentences_, type_='word'):
        """ Returns sequence of idicies corresponding to data set sentences.

        Given a dictionary of type:idx key, value pairs, returns the sequence
        of idx corresponding to the type order in sentences. Type can be the
        word types or tag types of Dataset instance.

        Args:
            types: a dictionary of type, idx key value pairs
            sentences: a list of lists, where each list represents a sentence
                for the Dataset instance and each sublist contains tuples of
                type and tag.

        Returns:
            a list, containing a sequence of idx's corresponding to the type
            order in sentences.

        Preconditions:
            assumes that the first column of the data set contains the word
            types, and the last column contains the tag types.
        """
        # column_idx and pad are different for word types and tag types

        # word type
        column_idx = 0
        pad = 0
        type_to_idx_ = self.word_type_to_index
        # tag type
        if type_ == 'tag':
            column_idx = -1
            pad = self.tag_type_to_index['O']
            type_to_idx_ = self.tag_type_to_index

        # get sequence of idx's in the order they appear in sentences
        type_sequence = [[type_to_idx_[ty[column_idx]] for ty in s] for s in sentences_]
        type_sequence = pad_sequences(maxlen=self.max_seq_len, sequences=type_sequence,
                                      padding='post', value=pad)
        return type_sequence

    def _tag_idx_sequence_to_categorical(self, partition='train'):
        """ Converts a class vector (integers) to n_class class matrix.

        Converts a class vector (integers) to n_class class matrix. The
        num_classes agument is determined by self.tag_type_count.

        Args:
            partition: which partition to be used, 'train' or 'test'

        Returns:
            n_class matrix representation of the input.
        """
        assert partition == 'train' or partition == 'test', '''keyword arg,
        partition, must be either 'train' or 'test' '''

        if partition == 'train':
            return [to_categorical(i, num_classes=self.tag_type_count) for i in
                    self.train_tag_idx_sequence]
        return [to_categorical(i, num_classes=self.tag_type_count) for i in
                self.test_tag_idx_sequence]
