#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
TensorFlow Helper functions.
"""

from __future__ import unicode_literals

import tensorflow as tf
from tensorflow.python.framework import dtypes
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import control_flow_ops
from tensorflow.python.ops import rnn
from tensorflow.python.ops import rnn_cell
from tensorflow.python.ops import variable_scope as vs
from tensorflow.models.rnn.seq2seq import embedding_attention_decoder


class TFModel(object):
    """An interface / methods wrapper for all TF models, used to load and save parameters."""

    def __init__(self, scope_name=None):
        """Just set variable scope name.
        @param scope_name: preferred variable scope name (may be None)
        """
        self.scope_name = scope_name

    def get_all_settings(self):
        """Get all settings except the trained model parameters (to be stored in a pickle)."""
        raise NotImplementedError()

    def load_all_settings(self, settings_dict):
        """Load all settings (except trained parameters) from a dictionary in the format provided
        by `get_all_settings`."""
        self.__dict__.update(settings_dict)

    def get_model_params(self):
        """Return the current model parameters in a dictionary (out of TensorFlow). Calls
        `var.eval()` on each model parameter.

        @return: all model parameters (variables), as numpy arrays, keyed in a dictionary under \
            their names
        """
        all_vars = tf.all_variables()
        ret = {}
        for var in all_vars:
            if not var.name.startswith(self.scope_name):  # skip variables not in my scope
                continue
            ret[var.name] = var.eval(session=self.session)
        return ret

    def set_model_params(self, vals):
        """Using a dictionary in the format returned by `get_model_params`, assign new parameter
        values.

        @param vals: a dictionary of new parameter values, as numpy arrays, keyed und their names \
            in a dictionary.
        """
        all_vars = tf.all_variables()
        for var in all_vars:
            if not var.name.startswith(self.scope_name):  # skip variables not in my scope
                continue
            if var.name in vals:
                op = var.assign(vals[var.name])
                self.session.run(op)


def embedding_attention_seq2seq_context(encoder_inputs, decoder_inputs, cell,
                                        num_encoder_symbols, num_decoder_symbols,
                                        num_heads=1, output_projection=None,
                                        feed_previous=False, dtype=dtypes.float32,
                                        scope=None):
    """A seq2seq architecture with two encoders, one for context, one for input DA. The decoder
    uses twice the cell size. Code adapted from TensorFlow examples."""

    with vs.variable_scope(scope or "embedding_attention_seq2seq_context"):

        # split context and real inputs into separate vectors
        context_inputs = encoder_inputs[0:len(encoder_inputs)/2]
        encoder_inputs = encoder_inputs[len(encoder_inputs)/2:]

        # build separate encoders
        encoder_cell = rnn_cell.EmbeddingWrapper(cell, num_encoder_symbols)
        with vs.variable_scope("context_rnn") as scope:
            context_outputs, context_states = rnn.rnn(
                    encoder_cell, context_inputs, dtype=dtype, scope=scope)
        with vs.variable_scope("input_rnn") as scope:
            encoder_outputs, encoder_states = rnn.rnn(
                    encoder_cell, encoder_inputs, dtype=dtype, scope=scope)

        # concatenate outputs & states
        encoder_outputs = [array_ops.concat(1, [co, eo], name="context-and-encoder-output")
                           for co, eo in zip(context_outputs, encoder_outputs)]
        encoder_states = [array_ops.concat(1, [cs, es], name="context-and-encoder-state")
                          for cs, es in zip(context_states, encoder_states)]

        # calculate a concatenation of encoder outputs to put attention on.
        top_states = [array_ops.reshape(e, [-1, 1, cell.output_size * 2])
                      for e in encoder_outputs]
        attention_states = array_ops.concat(1, top_states)

        # change the decoder cell to accommodate wider input
        # TODO this will work for BasicLSTMCell and GRUCell, but not for others
        cell = type(cell)(num_units=(cell.input_size * 2))

        # Decoder.
        output_size = None
        if output_projection is None:
            cell = rnn_cell.OutputProjectionWrapper(cell, num_decoder_symbols)
            output_size = num_decoder_symbols

        if isinstance(feed_previous, bool):
            return embedding_attention_decoder(
                    decoder_inputs, encoder_states[-1], attention_states, cell,
                    num_decoder_symbols, num_heads, output_size, output_projection,
                    feed_previous)
        else:    # If feed_previous is a Tensor, we construct 2 graphs and use cond.
            outputs1, states1 = embedding_attention_decoder(
                    decoder_inputs, encoder_states[-1], attention_states, cell,
                    num_decoder_symbols, num_heads, output_size, output_projection, True)
            vs.get_variable_scope().reuse_variables()
            outputs2, states2 = embedding_attention_decoder(
                    decoder_inputs, encoder_states[-1], attention_states, cell,
                    num_decoder_symbols, num_heads, output_size, output_projection, False)

            outputs = control_flow_ops.cond(feed_previous,
                                            lambda: outputs1, lambda: outputs2)
            states = control_flow_ops.cond(feed_previous,
                                           lambda: states1, lambda: states2)
            return outputs, states
