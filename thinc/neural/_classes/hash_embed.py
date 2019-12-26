from .model import Model
from ... import describe
from ..util import copy_array


def _uniform_init(lo, hi):
    def wrapped(W, ops):
        if (W ** 2).sum() == 0.0:
            copy_array(W, ops.xp.random.uniform(lo, hi, W.shape))

    return wrapped


@describe.attributes(
    nO=describe.Dimension("Vector dimensions"),
    nV=describe.Dimension("Number of vectors"),
    vectors=describe.Weights(
        "Embedding table", lambda obj: (obj.nV, obj.nO), _uniform_init(-0.1, 0.1)
    ),
    d_vectors=describe.Gradient("vectors"),
)
class HashEmbed(Model):
    name = "hash-embed"

    def __init__(self, nO, nV, seed=None, column=0, **kwargs):
        Model.__init__(self, **kwargs)
        self.column = column
        self.nO = nO
        self.nV = nV

        if seed is not None:
            self.seed = seed
        else:
            self.seed = self.id

    def predict(self, ids):
        if ids.ndim >= 2:
            ids = self.ops.xp.ascontiguousarray(ids[:, self.column], dtype="uint64")
        keys = self.ops.hash(ids, self.seed) % self.nV
        vectors = self.vectors[keys]
        summed = vectors.sum(axis=1)
        return summed

    def begin_update(self, ids):
        if ids.ndim >= 2:
            ids = self.ops.xp.ascontiguousarray(ids[:, self.column], dtype="uint64")
        keys = self.ops.hash(ids, self.seed) % self.nV
        vectors = self.vectors[keys].sum(axis=1)

        def finish_update(delta):
            if mask is not None:
                delta *= mask
            keys = self.ops.hash(ids, self.seed) % self.nV
            d_vectors = self.d_vectors
            keys = self.ops.xp.ascontiguousarray(keys.T, dtype="i")
            for i in range(keys.shape[0]):
                self.ops.scatter_add(d_vectors, keys[i], delta)
            if sgd is not None:
                sgd(self._mem.weights, self._mem.gradient, key=self.id)
            return None

        return vectors, finish_update
