import numpy

import chainer
from chainer.backends import cuda


class WalkerAlias(object):
    """Implementation of Walker's alias method.

    This method generates a random sample from given probabilities
    :math:`p_1, \\dots, p_n` in :math:`O(1)` time.
    It is more efficient than :func:`~numpy.random.choice`.
    This class works on both CPU and GPU.

    Args:
        probs (float list): Probabilities of entries. They are normalized with
                            `sum(probs)`.

    See: `Wikipedia article <https://en.wikipedia.org/wiki/Alias_method>`_

    """

    def __init__(self, probs):
        prob = numpy.array(probs, numpy.float32)
        prob /= numpy.sum(prob)
        threshold = numpy.ndarray(len(probs), numpy.float32)
        values = numpy.ndarray(len(probs) * 2, numpy.int32)
        il, ir = 0, 0
        pairs = list(zip(prob, range(len(probs))))
        pairs.sort()
        for prob, i in pairs:
            p = prob * len(probs)
            while p > 1 and ir < il:
                values[ir * 2 + 1] = i
                p -= 1.0 - threshold[ir]
                ir += 1
            threshold[il] = p
            values[il * 2] = i
            il += 1
        # fill the rest
        for i in range(ir, len(probs)):
            values[i * 2 + 1] = 0

        assert((values < len(threshold)).all())
        self.threshold = threshold
        self.values = values
        self._device = chainer.get_device(numpy)

    @property
    def device(self):
        return self._device

    @property
    def use_gpu(self):
        raise AttributeError(
            'WalkerAlias.use_gpu attribute has been removed. Use '
            'WalkerAlias.device attribute instead.')

    def to_device(self, device):
        device = chainer.get_device(device)
        self.threshold = device.send(self.threshold)
        self.values = device.send(self.values)
        self._device = device
        return self

    def to_gpu(self):
        """Make a sampler GPU mode.

        """
        return self.to_device(cuda.Device())

    def to_cpu(self):
        """Make a sampler CPU mode.

        """
        return self.to_device(numpy)

    def sample(self, shape):
        """Generates a random sample based on given probabilities.

        Args:
            shape (tuple of int): Shape of a return value.

        Returns:
            Returns a generated array with the given shape. If a sampler is in
            CPU mode the return value is a :class:`numpy.ndarray` object, and
            if it is in GPU mode the return value is a :class:`cupy.ndarray`
            object.
        """
        xp = self._device.xp
        if xp is cuda.cupy:
            return self.sample_gpu(shape)
        elif xp is numpy:
            return self.sample_cpu(shape)
        else:
            # TODO(niboshi): Support ChainerX
            raise NotImplementedError(
                'WalkerAlias does not support device: {}'.format(self._device))

    def sample_cpu(self, shape):
        ps = numpy.random.uniform(0, 1, shape)
        pb = ps * len(self.threshold)
        index = pb.astype(numpy.int32)
        left_right = (self.threshold[index] < pb - index).astype(numpy.int32)
        return self.values[index * 2 + left_right]

    def sample_gpu(self, shape):
        ps = cuda.cupy.random.uniform(size=shape, dtype=numpy.float32)
        vs = cuda.elementwise(
            'T ps, raw T threshold , raw S values, int32 b',
            'int32 vs',
            '''
            T pb = ps * b;
            int index = __float2int_rd(pb);
            // fill_uniform sometimes returns 1.0, so we need to check index
            if (index >= b) {
              index = 0;
            }
            int lr = threshold[index] < pb - index;
            vs = values[index * 2 + lr];
            ''',
            'walker_alias_sample'
        )(ps, self.threshold, self.values, len(self.threshold))
        return vs
