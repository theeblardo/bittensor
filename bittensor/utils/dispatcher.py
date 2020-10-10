import torch
import numpy as np
from typing import List, Tuple, Dict, Optional



class Dispatcher(object):
    """Helper for implementing a mixture of experts.
    The purpose of this class is to create input minibatches for the
    experts and to combine the results of the experts to form a unified
    output tensor.
    There are two functions:
    dispatch - take an input Tensor and create input Tensors for each expert.
    combine - take output Tensors from each expert and form a combined output
      Tensor.  Outputs from different experts for the same batch element are
      summed together, weighted by the provided "gates".
    The class is initialized with a "gates" Tensor, which specifies which
    batch elements go to which experts, and the weights to use when combining
    the outputs.  Batch element b is sent to expert e iff gates[b, e] != 0.
    The inputs and outputs are all two-dimensional [batch, depth].
    Caller is responsible for collapsing additional dimensions prior to
    calling this class and reshaping the output to the original shape.
    See common_layers.reshape_like().
    Example use:
    gates: a float32 `Tensor` with shape `[batch_size, num_experts]`
    inputs: a float32 `Tensor` with shape `[batch_size, input_size]`
    experts: a list of length `num_experts` containing sub-networks.
    dispatcher = SparseDispatcher(num_experts, gates)
    expert_inputs = dispatcher.dispatch(inputs)
    expert_outputs = [experts[i](expert_inputs[i]) for i in range(num_experts)]
    outputs = dispatcher.combine(expert_outputs)
    The preceding code sets the output for a particular example b to:
    output[b] = Sum_i(gates[b, i] * experts[i](inputs[b]))
    This class takes advantage of sparsity in the gate matrix by including in the
    `Tensor`s for expert i only the batch elements for which `gates[b, i] > 0`.
    """

    def __init__(self):
        """Create a SparseDispatcher."""
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
      
    def dispatch(self, x: object, gates) -> List[ object ]:
        # sort experts
        sorted_experts, index_sorted_experts = torch.nonzero(gates).sort(0)

        # drop indices
        _, self._expert_index = sorted_experts.split(1, dim=1)

        # get according batch index for each expert
        batch_index = sorted_experts[index_sorted_experts[:, 1], 0]

        # calculate num samples that each expert gets
        part_sizes = list((gates != 0.0).sum(0).cpu().numpy())
        
        results = []
        if isinstance(x, list):   
          batch_index = batch_index.view(-1, gates.shape[0])
          for i, row in enumerate(batch_index):
            results.append([])
            for _, idx in enumerate(row):
              results[i].append( x[idx] ) 
        else:
          # expand according to batch index so we can just split by _part_sizes
          x_expanded = x[batch_index].to(self.device)
          results = torch.split(x_expanded, part_sizes, dim=0)
      
        return results 
        

    def combine(self, expert_out, gates, multiply_by_gates=True):
        """Sum together the expert output, weighted by the gates.
        The slice corresponding to a particular batch element `b` is computed
        as the sum over all experts `i` of the expert output, weighted by the
        corresponding gate values.  If `multiply_by_gates` is set to False, the
        gate values are ignored.
        Args:
          expert_out: a list of `num_experts` `Tensor`s, each with shape
            `[expert_batch_size_i, <extra_output_dims>]`.
          multiply_by_gates: a boolean
        Returns:
          a `Tensor` with shape `[batch_size, <extra_output_dims>]`.
        """

        # apply exp to expert outputs, so we are not longer in log space
        stitched = torch.cat(expert_out, 0).to(self.device)
        flat_stitched = torch.flatten(stitched, start_dim=1)

        if multiply_by_gates:

            # sort experts
            sorted_experts, index_sorted_experts = torch.nonzero(gates).sort(0)

            # drop indices
            _, expert_index = sorted_experts.split(1, dim=1)

            # get according batch index for each expert
            batch_index = sorted_experts[index_sorted_experts[:, 1], 0]

            gates_exp = gates[batch_index.flatten()]

            nonzero_gates = torch.gather(gates_exp, 1, expert_index).to(self.device)

            flat_stitched = torch.flatten(stitched, start_dim=1)

            flat_stitched = flat_stitched.mul(nonzero_gates)


        zeros = torch.zeros(gates.size(0),
                            flat_stitched.size(1),
                            requires_grad=True).to(self.device)

        # combine samples that have been processed by the same k experts
        combined = zeros.index_add(0, batch_index, flat_stitched.float())

        # reshape as original
        combined = combined.view(expert_out[0].shape)

        return combined
