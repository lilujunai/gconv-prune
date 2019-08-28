""" ResNet model definition for CIFAR-10/100 datasets.

References:
- https://github.com/facebook/fb.resnet.torch
- https://github.com/pytorch/vision/blob/master/torchvision/models/resnet.py
- https://github.com/bearpaw/pytorch-classification/blob/master/models/cifar/resnet.py
"""

from __future__ import absolute_import

import torch.nn as nn
import numpy as np

from gumi.ops.group_conv2d import GroupConv2d
from gumi.ops.mask_conv2d import MaskConv2d

# methods to be exposed
__all__ = [
    'ResNet',
    'resnet110',
    'resnet110m',
    'resnet110g4',
    'resnet110g8',
    'resnet110g4r',
    'resnet110g8r',
    'resnet110g4t',
    'resnet110g8t',
]


def _get_indices(indices, channels, num_groups=None):
  """ Create a list of indices from a given instructor.
  
  - If indices is a list, return a list;
  - If indices is a str, return a list created based on the content
    of the string;
  - If indices is None, return None.

  Args:
    indices(object)
    channels(int): number of channels
  Returns:
    A list of indices.
  """
  if indices is None:
    return None

  if isinstance(indices, list):
    return indices

  if isinstance(indices, str):
    if indices == 'random':
      return np.random.permutation(channels).tolist()

    if indices == 'trans':
      assert isinstance(num_groups, int)
      perm = np.arange(channels)
      perm = perm.reshape((channels // num_groups, num_groups))
      perm = perm.T.reshape(channels)
      return perm.tolist()

    raise ValueError('Indices pattern {} cannot be recognised.'.format(indices))

  raise TypeError('Cannot recognise type of indices: {}'.format(type(indices)))


def conv3x3(in_planes, out_planes, groups=1, stride=1, indices=None,
            mask=False):
  """ 3x3 convolution with padding, support mask and group """
  if not mask:
    return GroupConv2d(
        in_planes,
        out_planes,
        kernel_size=3,
        stride=stride,
        padding=1,
        num_groups=groups,
        indices=_get_indices(indices, out_planes, num_groups=groups))
  else:
    return MaskConv2d(
        in_planes,
        out_planes,
        kernel_size=3,
        stride=stride,
        padding=1,
        bias=False)


def conv1x1(in_planes, out_planes, stride=1, groups=1, indices=None,
            mask=False):
  """ 1x1 convolution """
  if not mask:
    return GroupConv2d(
        in_planes,
        out_planes,
        kernel_size=1,
        stride=stride,
        num_groups=groups,
        indices=_get_indices(indices, out_planes, num_groups=groups))
  else:
    return MaskConv2d(
        in_planes, out_planes, kernel_size=1, stride=stride, bias=False)


class BasicBlock(nn.Module):
  """ The stacked convolution block design.

  Structure:
    [in_planes] -> conv3x3 -> [planes] -> conv3x3 -> [planes]
  """
  expansion = 1

  def __init__(self,
               in_planes,
               planes,
               stride=1,
               downsample=None,
               groups=1,
               indices=None,
               mask=False):
    """ CTOR.
    
    Args:
      in_planes(int): input channels
      planes(int): final output channels
      stride(int)
      downsample(func): downsample function
      groups(int): number of groups
      indices(list): a permutation
      mask(bool): whether to build masked convolution
    """
    super(BasicBlock, self).__init__()
    self.conv1 = conv3x3(
        in_planes, planes, groups, stride, indices=indices, mask=mask)
    self.bn1 = nn.BatchNorm2d(planes)
    self.relu = nn.ReLU(inplace=True)
    self.conv2 = conv3x3(planes, planes, groups, indices=indices, mask=mask)
    self.bn2 = nn.BatchNorm2d(planes)

    self.downsample = downsample
    self.stride = stride

  def forward(self, x):
    residual = x

    out = self.conv1(x)
    out = self.bn1(out)
    out = self.relu(out)

    out = self.conv2(out)
    out = self.bn2(out)

    if self.downsample is not None:
      residual = self.downsample(x)

    out += residual  # shortcut
    out = self.relu(out)

    return out


class Bottleneck(nn.Module):
  """ Bottleneck block with expansion > 1.
  
  Structure:
    [in_planes] -> conv1x1 -> [planes] -> conv3x3 -> [planes] -> conv1x1 -> [planes x 4]
  """
  expansion = 4

  def __init__(self,
               in_planes,
               planes,
               stride=1,
               downsample=None,
               groups=1,
               indices=None,
               mask=False):
    """ CTOR.
    
    Args:
      in_planes(int): input channels
      planes(int): final output channels
      stride(int)
      downsample(func): downsample function
    """

    super(Bottleneck, self).__init__()
    self.conv1 = conv1x1(
        in_planes, planes, groups=groups, indices=indices, mask=mask)
    self.bn1 = nn.BatchNorm2d(planes)
    self.conv2 = conv3x3(
        planes,
        planes,
        stride=stride,
        groups=groups,
        indices=indices,
        mask=mask)
    self.bn2 = nn.BatchNorm2d(planes)
    self.conv3 = conv1x1(
        planes,
        planes * self.expansion,
        groups=groups,
        indices=indices,
        mask=mask)
    self.bn3 = nn.BatchNorm2d(planes * self.expansion)
    self.relu = nn.ReLU(inplace=True)

    self.downsample = downsample
    self.stride = stride

  def forward(self, x):
    residual = x

    out = self.conv1(x)
    out = self.bn1(out)
    out = self.relu(out)

    out = self.conv2(out)
    out = self.bn2(out)
    out = self.relu(out)

    out = self.conv3(out)
    out = self.bn3(out)

    if self.downsample is not None:
      residual = self.downsample(x)

    out += residual
    out = self.relu(out)

    return out


class ResNet(nn.Module):
  """ The ResNet model designed for CIFAR-10/100.

  Depth specified for this module should satisfy the constraint
  mentioned in Section 4.2 of the original paper. 

  You can use depth to configure the stem of the ResNet model,
  and num_classes to adapt to CIFAR-10/100.

  Note:
    You can use groups to configure all convolution layers with
    a uniform group number.
    The first Conv2d layer will not be grouped.

  Attributes:
    in_planes(int): number of input channels for the current layer 
  """

  def __init__(self,
               block,
               depth,
               groups=1,
               indices=None,
               mask=False,
               num_classes=10):
    """ CTOR.
    Args:
      block(class): BasicBlock or BottleneckBlock
      depth(int): number of conv2d layers
      groups(int): number of groups
      indices(object): indices configuration
      num_classes(int): number of classes
    """
    super(ResNet, self).__init__()

    # Model type specifies number of layers for CIFAR-10 model
    assert (depth - 2) % 6 == 0, 'depth should be 6n+2'
    assert isinstance(groups, int)

    n = (depth - 2) // 6

    # block = Bottleneck if depth >= 44 else BasicBlock  # WHY?

    self.in_planes = 16
    self.num_groups = groups
    self.indices = indices
    self.mask = mask

    # first convolution
    self.conv1 = conv3x3(3, self.in_planes)
    self.bn1 = nn.BatchNorm2d(self.in_planes)
    self.relu = nn.ReLU(inplace=True)

    # core topology
    self.layer1 = self._make_layer(block, 16, n)
    self.layer2 = self._make_layer(block, 32, n, stride=2)
    self.layer3 = self._make_layer(block, 64, n, stride=2)

    # final layers
    # 8 is the resolution of the final feature map
    self.avgpool = nn.AvgPool2d(8)
    self.fc = nn.Linear(8 * 8 * block.expansion, num_classes)

    # initialisation
    for m in self.modules():
      if isinstance(m, nn.Conv2d):
        nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
      elif isinstance(m, nn.BatchNorm2d):
        nn.init.constant_(m.weight, 1)
        nn.init.constant_(m.bias, 0)

  def _make_layer(self, block, planes, blocks, stride=1):
    """ Create duplicated blocks in ResNet at a specific resolution.

    layer = a set of sequential blocks

    Note:
      It has a side-effect of updating the value of in_planes.
      self.in_planes is the # input channels to the very first
      block of the current layer.
    Note:
      self.groups will be used to configure all layers.
    
    Args:
      block(class): the block to be duplicated
      planes(int): number of input channels
      blocks(int): number of blocks
      stride(int)
    Returns:
      A nn.Module of all blocks
    """
    downsample = None

    # determine whether we need to downsample within shortcut
    # - if stride != 1, main branch is downsampled spatially
    # - in_planes != planes * expansion, this downsample method simply
    #   expands the channels.
    if stride != 1 or self.in_planes != planes * block.expansion:
      downsample = nn.Sequential(
          conv1x1(
              self.in_planes,
              planes * block.expansion,
              stride=stride,
              groups=self.num_groups,
              indices=self.indices,
              mask=self.mask),
          nn.BatchNorm2d(planes * block.expansion),
      )

    layers = [None] * blocks
    layers[0] = block(
        self.in_planes,
        planes,
        stride=stride,
        downsample=downsample,
        groups=self.num_groups,
        indices=self.indices,
        mask=self.mask)

    self.in_planes = planes * block.expansion
    for i in range(1, blocks):
      layers[i] = block(
          self.in_planes,
          planes,
          groups=self.num_groups,
          indices=self.indices,
          mask=self.mask)

    return nn.Sequential(*layers)

  def forward(self, x):
    x = self.conv1(x)
    x = self.bn1(x)
    x = self.relu(x)  # 32x32

    x = self.layer1(x)  # 32x32
    x = self.layer2(x)  # 16x16
    x = self.layer3(x)  # 8x8

    x = self.avgpool(x)
    x = x.view(x.size(0), -1)
    x = self.fc(x)

    return x


def resnet110(**kwargs):
  """ Constructs a ResNet-110 model for CIFAR-10/100.
  
  Returns:
    A ResNet instance.
  """
  return ResNet(BasicBlock, 110, **kwargs)


def resnet110m(**kwargs):
  """ Constructs a ResNet-110 model for CIFAR-10/100 with masked weights.
  
  Returns:
    A ResNet instance.
  """
  return ResNet(BasicBlock, 110, mask=True, **kwargs)


def resnet110g4(**kwargs):
  """ Constructs a ResNet-110 model with 4 groups for CIFAR-10/100.
  
  Returns:
    A ResNet instance.
  """
  return ResNet(BasicBlock, 110, groups=4, **kwargs)


def resnet110g8(**kwargs):
  """ Constructs a ResNet-110 model with 8 groups for CIFAR-10/100.
  
  Returns:
    A ResNet instance.
  """
  return ResNet(BasicBlock, 110, groups=8, **kwargs)


def resnet110g4r(**kwargs):
  """ Constructs a ResNet-110 model with 4 groups and random permutation
     for CIFAR-10/100.
  
  Returns:
    A ResNet instance.
  """
  return ResNet(BasicBlock, 110, groups=4, indices='random', **kwargs)


def resnet110g8r(**kwargs):
  """ Constructs a ResNet-110 model with 8 groups and random permutation
   for CIFAR-10/100.
  
  Returns:
    A ResNet instance.
  """
  return ResNet(BasicBlock, 110, groups=8, indices='random', **kwargs)


def resnet110g4t(**kwargs):
  """ Constructs a ResNet-110 model with 4 groups and transposed permutation
     for CIFAR-10/100.
  
  Returns:
    A ResNet instance.
  """
  return ResNet(BasicBlock, 110, groups=4, indices='trans', **kwargs)


def resnet110g8t(**kwargs):
  """ Constructs a ResNet-110 model with 8 groups and transposed permutation
   for CIFAR-10/100.
  
  Returns:
    A ResNet instance.
  """
  return ResNet(BasicBlock, 110, groups=8, indices='trans', **kwargs)


def resnet164(**kwargs):
  return ResNet(BasicBlock, 164, **kwargs)


def resnet164m(**kwargs):
  return ResNet(BasicBlock, 164, mask=True, **kwargs)
