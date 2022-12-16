import torch
from torch.nn import functional as F

from .networks import MLPNetwork
from .rnd import RND


class E2S_NovelD(RND):
    """ Elliptical Episodic Scaling of NovelD. """

    def __init__(self, input_dim, enc_dim, hidden_dim, 
                 scale_fac=0.5, ridge=0.1, lr=1e-4, device="cpu"):
        super(E2S_NovelD, self).__init__(
            input_dim, enc_dim, hidden_dim, lr, device)
        self.scale_fac = scale_fac
        self.ridge = ridge
        # Last state novelty
        self.last_nov = None
        # Inverse covariance matrix for Elliptical bonus
        self.inv_cov = torch.eye(input_dim).to(device) * (1.0 / self.ridge)
        self.outer_product_buffer = torch.empty(
            input_dim, input_dim).to(device)
    
    def init_new_episode(self):
        self.last_nov = None
        self.inv_cov = torch.eye(self.input_dim).to(self.device)
        self.inv_cov *= (1.0 / self.ridge)

    def set_eval(self, device):
        super().set_eval(device)
        self.inv_cov = self.inv_cov.to(device)
        self.outer_product_buffer = self.outer_product_buffer.to(device)
        
    def get_reward(self, state):
        """
        Get intrinsic reward for the given state.
        Inputs:
            state (torch.Tensor): State from which to generate the reward,
                dim=(1, state_dim).
        Outputs:
            int_reward (float): Intrinsic reward for the input state.
        """
        # Get RND reward as novelty
        nov = super().get_reward(state)

        # Compute reward
        if self.last_nov is not None:
            int_reward = max(nov - self.scale_fac * self.last_nov, 0.0)
        else:
            int_reward = 0.0

        self.last_nov = nov

        # Compute the elliptic scale
        u = torch.mv(self.inv_cov, state.squeeze())
        elliptic_scale = torch.dot(state.squeeze(), u).item()
        # Update covariance matrix
        torch.outer(u, u, out=self.outer_product_buffer)
        torch.add(
            self.inv_cov, self.outer_product_buffer, 
            alpha=-(1. / (1. + elliptic_scale)), out=self.inv_cov)

        return int_reward * elliptic_scale

# class E2S_NovelD(NovelD):
#     """ Elliptical Episodic Scaling of Random Network Distillation. """

#     def __init__(self, input_dim, enc_dim, hidden_dim, 
#                  ridge=0.1, scale_fac=0.5, lr=1e-4, device="cpu"):
#         super(E2S_NovelD, self).__init__(
#             input_dim, enc_dim, hidden_dim, lr, scale_fac, device)
#         self.ridge = ridge
#         # Inverse covariance matrix for Elliptical bonus
#         self.inv_cov = torch.eye(input_dim).to(device) * (1.0 / self.ridge)
#         self.outer_product_buffer = torch.empty(
#             input_dim, input_dim).to(device)
    
#     def init_new_episode(self):
#         super().init_new_episode()
#         self.inv_cov = torch.eye(self.input_dim).to(self.device)
#         self.inv_cov *= (1.0 / self.ridge)

#     def set_eval(self, device):
#         super().set_eval(device)
#         self.inv_cov = self.inv_cov.to(device)
#         self.outer_product_buffer = self.outer_product_buffer.to(device)
        
#     def get_reward(self, state):
#         """
#         Get intrinsic reward for the given state.
#         Inputs:
#             state (torch.Tensor): State from which to generate the reward,
#                 dim=(1, state_dim).
#         Outputs:
#             int_reward (float): Intrinsic reward for the input state.
#         """
#         # Get NovelD reward
#         int_reward = super().get_reward(state)

#         # Compute the elliptic scale
#         u = torch.mv(self.inv_cov, state.squeeze())
#         elliptic_scale = torch.dot(state.squeeze(), u).item()
#         # Update covariance matrix
#         torch.outer(u, u, out=self.outer_product_buffer)
#         torch.add(
#             self.inv_cov, self.outer_product_buffer, 
#             alpha=-(1. / (1. + elliptic_scale)), out=self.inv_cov)

#         return int_reward * elliptic_scale