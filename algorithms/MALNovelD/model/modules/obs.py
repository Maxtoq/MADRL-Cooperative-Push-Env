import torch

from torch import nn

from .networks import MLPNetwork


class ObservationEncoder(nn.Module):
    """
    Network that encodes an observation into a context embedding.
    """
    def __init__(self, obs_dim, embedding_dim, hidden_dim, n_hidden_layers=1):
        """
        Inputs:
            :param obs_dim (int): Dimension of the input observation.
            :param embedding_dim (int): Dimension of the output embedding.
            :param hidden_dim (int): Dimension of the hidden layers.
            :param n_hidden_layers (int): Number of hidden layers.
        """
        super(ObservationEncoder, self).__init__()
        self.mlp = MLPNetwork(
            obs_dim, embedding_dim, hidden_dim, n_layers=n_hidden_layers)

    def forward(self, obs_batch):
        """
        Forward pass of the network.
        Inputs:
            :param obs_batch (torch.Tensor): Batch of observation, 
                dim=(batch_size, obs_dim)
        Outputs:
            :param out (torch.Tensor): Batch of correponsding context 
                embeddings, dim=(batch_size, embedding_dim).
        """
        return self.mlp(obs_batch)