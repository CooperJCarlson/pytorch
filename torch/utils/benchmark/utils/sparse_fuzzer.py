import math
from numbers import Number
from typing import Optional, Tuple, Union

import torch
from torch.utils.benchmark import FuzzedTensor


class FuzzedSparseTensor(FuzzedTensor):
    def __init__(
        self,
        name: str,
        size: Tuple[Union[str, int], ...],
        min_elements: Optional[int] = None,
        max_elements: Optional[int] = None,
        dim_parameter: Optional[str] = None,
        sparse_dim: Optional[str] = None,
        nnz: Optional[str] = None,
        density: Optional[str] = None,
        coalesced: Optional[str] = None,
        dtype=torch.float32,
        cuda=False,
    ):
        """
        Args:
            name:
                A string identifier for the generated Tensor.
            size:
                A tuple of integers or strings specifying the size of the generated
                Tensor. String values will replaced with a concrete int during the
                generation process, while ints are simply passed as literals.
            min_elements:
                The minimum number of parameters that this Tensor must have for a
                set of parameters to be valid. (Otherwise they are resampled.)
            max_elements:
                Like `min_elements`, but setting an upper bound.
            dim_parameter:
                The length of `size` will be truncated to this value.
                This allows Tensors of varying dimensions to be generated by the
                Fuzzer.
            sparse_dim:
                The number of sparse dimensions in a sparse tensor.
            density:
                This value allows tensors of varying sparsities to be generated by the Fuzzer.
            coalesced:
                The sparse tensor format permits uncoalesced sparse tensors,
                where there may be duplicate coordinates in the indices.
            dtype:
                The PyTorch dtype of the generated Tensor.
            cuda:
                Whether to place the Tensor on a GPU.
        """
        super().__init__(
            name=name,
            size=size,
            min_elements=min_elements,
            max_elements=max_elements,
            dim_parameter=dim_parameter,
            dtype=dtype,
            cuda=cuda,
        )
        self._density = density
        self._coalesced = coalesced
        self._sparse_dim = sparse_dim

    @staticmethod
    def sparse_tensor_constructor(size, dtype, sparse_dim, nnz, is_coalesced):
        """sparse_tensor_constructor creates a sparse tensor with coo format.

        Note that when `is_coalesced` is False, the number of elements is doubled but the number of indices
        represents the same amount of number of non zeros `nnz`, i.e, this is virtually the same tensor
        with the same sparsity pattern. Moreover, most of the sparse operation will use coalesce() method
        and what we want here is to get a sparse tensor with the same `nnz` even if this is coalesced or not.

        In the other hand when `is_coalesced` is True the number of elements is reduced in the coalescing process
        by an unclear amount however the probability to generate duplicates indices are low for most of the cases.
        This decision was taken on purpose to maintain the construction cost as low as possible.
        """
        if isinstance(size, Number):
            size = [size] * sparse_dim
        assert (
            all(size[d] > 0 for d in range(sparse_dim)) or nnz == 0
        ), "invalid arguments"
        v_size = [nnz] + list(size[sparse_dim:])
        if dtype.is_floating_point:
            v = torch.rand(size=v_size, dtype=dtype, device="cpu")
        else:
            v = torch.randint(1, 127, size=v_size, dtype=dtype, device="cpu")

        i = torch.rand(sparse_dim, nnz, device="cpu")
        i.mul_(torch.tensor(size[:sparse_dim]).unsqueeze(1).to(i))
        i = i.to(torch.long)

        if not is_coalesced:
            v = torch.cat([v, torch.randn_like(v)], 0)
            i = torch.cat([i, i], 1)

        x = torch.sparse_coo_tensor(i, v, torch.Size(size))
        if is_coalesced:
            x = x.coalesce()
        return x

    def _make_tensor(self, params, state):
        size, _, _ = self._get_size_and_steps(params)
        density = params["density"]
        nnz = math.ceil(sum(size) * density)
        assert nnz <= sum(size)

        is_coalesced = params["coalesced"]
        sparse_dim = params["sparse_dim"] if self._sparse_dim else len(size)
        sparse_dim = len(size) if len(size) < sparse_dim else sparse_dim
        tensor = self.sparse_tensor_constructor(
            size, self._dtype, sparse_dim, nnz, is_coalesced
        )

        if self._cuda:
            tensor = tensor.cuda()
        sparse_dim = tensor.sparse_dim()
        dense_dim = tensor.dense_dim()
        is_hybrid = len(size[sparse_dim:]) > 0

        properties = {
            "numel": int(tensor.numel()),
            "shape": tensor.size(),
            "is_coalesced": tensor.is_coalesced(),
            "density": density,
            "sparsity": 1.0 - density,
            "sparse_dim": sparse_dim,
            "dense_dim": dense_dim,
            "is_hybrid": is_hybrid,
            "dtype": str(self._dtype),
        }
        return tensor, properties
