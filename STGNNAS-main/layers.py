import math
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.nn.init as init

from micro_search_space import act_map

class Align(nn.Module): 
    def __init__(self, c_in, c_out):
        super(Align, self).__init__()
        self.c_in = c_in
        self.c_out = c_out
        self.align_conv = nn.Conv2d(in_channels=self.c_in, out_channels=self.c_out, kernel_size=(1, 1))

    def forward(self, x): 
        if self.c_in > self.c_out:
            x_align = self.align_conv(x)
        elif self.c_in < self.c_out:
            batch_size, c_in, timestep, n_vertex = x.shape
            x_align = torch.cat([x, torch.zeros([batch_size, self.c_out - self.c_in, timestep, n_vertex]).to(x)], dim=1)
        else:
            x_align = x
        return x_align

class CausalConv1d(nn.Conv1d):
    def __init__(self, in_channels, out_channels, kernel_size, stride=1, enable_padding=False, dilation=1, groups=1, bias=True): #print("OliviaG") 5次
        # print("OliviaG")
        if enable_padding == True:
            self.__padding = (kernel_size - 1) * dilation
        else:
            self.__padding = 0
        super(CausalConv1d, self).__init__(in_channels, out_channels, kernel_size=kernel_size, stride=stride, padding=self.__padding, dilation=dilation, groups=groups, bias=bias)

class TemporalConvLayer(nn.Module): 

    # Temporal Convolution Layer (GLU)
    #
    #        |----------------- x_in --------------| * residual connection *
    #        |                                     |
    #        |    |--->--- casual conv -- x_p ---  + -------|       
    # -------|----|                                         ⊙ ------>
    #             |--->--- casual conv -- x_q-- sigmoid ----|                               
    #
    
    #param x: tensor, [batch_size, c_in, timestep, n_vertex]

    def __init__(self, Kt, c_in, c_out, n_vertex, gated_act_func, enable_gated_act_func, ratio): 
        super(TemporalConvLayer, self).__init__()
        self.Kt = Kt
        self.c_in = c_in
        self.c_out = c_out
        self.n_vertex = n_vertex
        self.gated_act_func = gated_act_func
        self.enable_gated_act_func = enable_gated_act_func
        self.ratio = ratio
        self.align = Align(self.c_in, self.c_out)
        if self.enable_gated_act_func == True:
            self.causal_conv = CausalConv1d(in_channels=self.c_in, out_channels=2 * self.c_out, kernel_size=(self.Kt, 1), enable_padding=False, dilation=1)
        else:
            self.causal_conv = CausalConv1d(in_channels=self.c_in, out_channels=self.c_out, kernel_size=(self.Kt, 1), enable_padding=False, dilation=1)
        self.linear = nn.Linear(self.n_vertex, self.n_vertex)
        self.sigmoid = nn.Sigmoid()
        self.tanh = nn.Tanh()
        self.softsign = nn.Softsign()
        self.relu = nn.ReLU()
        self.softplus = nn.Softplus()
        self.leakyrelu = nn.LeakyReLU()
        self.prelu = nn.PReLU()
        self.elu = nn.ELU()
        

    def forward(self, x):
        x_in = self.align(x)[:, :, self.Kt - 1:, :]
        x_causal_conv = self.causal_conv(x)

        if self.enable_gated_act_func == True:
            x_p = x_causal_conv[:, : self.c_out, :, :]
            x_q = x_causal_conv[:, -self.c_out:, :, :]


            # GLU was first purposed in
                # Language Modeling with Gated Convolutional Networks
                # https://arxiv.org/abs/1612.08083
                # Input tensor X was split by a certain dimension into tensor X_a and X_b
                # In original paper, GLU as Linear(X_a) ⊙ Sigmoid(Linear(X_b))
                # However, in PyTorch, GLU as X_a ⊙ Sigmoid(X_b)
                # https://pytorch.org/docs/master/nn.functional.html#torch.nn.functional.glu
                # Because in original paper, the representation of GLU and GTU are ambiguous
                # So, it is arguable which one version is correct

                

            # Temporal Convolution Layer (GLU)
            if self.gated_act_func == "glu":   

                if self.ratio == "one_one":
                # (x_p + x_in) ⊙ Sigmoid(x_q)         
                    x_tc_out = torch.mul((x_p + x_in), self.sigmoid(x_q))

                elif self.ratio == "one_two":
                    x_tc_out = torch.mul((x_p / 3 + 2 * x_in / 3), self.sigmoid(x_q))

                elif self.ratio == "two_one":
                    x_tc_out = torch.mul((2 * x_p / 3 + x_in / 3), self.sigmoid(x_q))

                elif self.ratio == "three_two":
                    x_tc_out = torch.mul((3 * x_p / 5 + 2 * x_in / 5), self.sigmoid(x_q))

                elif self.ratio == "two_three":
                    x_tc_out = torch.mul((2 * x_p / 5 + 3 * x_in / 5), self.sigmoid(x_q))

                elif self.ratio == "three_one":
                    x_tc_out = torch.mul((3 * x_p / 4 + x_in / 4), self.sigmoid(x_q))

                elif self.ratio == "one_three":
                    x_tc_out = torch.mul((x_p / 4 + 3 * x_in / 4), self.sigmoid(x_q))

            # Temporal Convolution Layer (GTU)
            elif self.gated_act_func == "gtu":

                if self.ratio == "one_one":
                # Tanh(x_p + x_in) ⊙ Sigmoid(x_q)
                    x_tc_out = torch.mul(self.tanh(x_p + x_in), self.sigmoid(x_q))

                elif self.ratio == "one_two":
                    x_tc_out = torch.mul(self.tanh(x_p / 3 + 2 * x_in / 3), self.sigmoid(x_q))
            
                elif self.ratio == "two_one":
                    x_tc_out = torch.mul(self.tanh(2 * x_p / 3 + x_in / 3), self.sigmoid(x_q))

                elif self.ratio == "three_two":
                    x_tc_out = torch.mul(self.tanh(3 * x_p / 5 + 2 * x_in / 5), self.sigmoid(x_q))
            
                elif self.ratio == "two_three":
                    x_tc_out = torch.mul(self.tanh(2 * x_p / 5 + 3 * x_in / 5), self.sigmoid(x_q))

                elif self.ratio == "three_one":
                    x_tc_out = torch.mul(self.tanh(3 * x_p / 4 + x_in / 4), self.sigmoid(x_q))
            
                elif self.ratio == "one_three":
                    x_tc_out = torch.mul(self.tanh(x_p / 4 + 3 * x_in / 4), self.sigmoid(x_q))
   
            else:
                raise ValueError(f'ERROR: activation function {self.act_func} is not defined.')

        else:
            x_tc_out = act_map(self.act_func)(x_causal_conv + x_in)

        return x_tc_out

class ChebConv(nn.Module): #√
    def __init__(self, c_in, c_out, Ks, chebconv_matrix, enable_bias, graph_conv_act_func): 
        super(ChebConv, self).__init__()
        self.c_in = c_in
        self.c_out = c_out
        self.Ks = Ks
        self.chebconv_matrix = chebconv_matrix
        self.enable_bias = enable_bias
        self.graph_conv_act_func = graph_conv_act_func
        self.weight = nn.Parameter(torch.FloatTensor(self.Ks, self.c_in, self.c_out))
        if self.enable_bias == True:
            self.bias = nn.Parameter(torch.FloatTensor(self.c_out))
        else:
            self.register_parameter('bias', None)
        self.initialize_parameters()

    def initialize_parameters(self):
        # For Sigmoid, Tanh or Softsign
        if self.graph_conv_act_func == 'sigmoid' or self.graph_conv_act_func == 'tanh' or self.graph_conv_act_func == 'softsign':
            init.xavier_uniform_(self.weight)

        # For ReLU, Softplus, Leaky ReLU, PReLU, or ELU
        elif self.graph_conv_act_func == 'relu' or self.graph_conv_act_func == 'softplus' or self.graph_conv_act_func == 'leakyrelu' \
            or self.graph_conv_act_func == 'prelu' or self.graph_conv_act_func == 'elu':
            init.kaiming_uniform_(self.weight)

        if self.bias is not None:
            _out_feats_bias = self.bias.size(0)
            stdv_b = 1. / math.sqrt(_out_feats_bias)
            init.uniform_(self.bias, -stdv_b, stdv_b)

    def forward(self, x): 
        batch_size, c_in, T, n_vertex = x.shape

        # Using recurrence relation to reduce time complexity from O(n^2) to O(K|E|),
        # where K = Ks - 1
        x = x.reshape(n_vertex, -1)
        x_0 = x
        x_1 = torch.mm(self.chebconv_matrix, x)
        if self.Ks - 1 < 0:
            raise ValueError(f'ERROR: the graph convolution kernel size Ks has to be a positive integer, but received {self.Ks}.')  
        elif self.Ks - 1 == 0:
            x_list = [x_0]
        elif self.Ks - 1 == 1:
            x_list = [x_0, x_1]
        elif self.Ks - 1 >= 2:
            x_list = [x_0, x_1]
            for k in range(2, self.Ks):
                x_list.append(torch.mm(2 * self.chebconv_matrix, x_list[k - 1]) - x_list[k - 2])
        x_tensor = torch.stack(x_list, dim=0)

        x_mul = torch.mm(x_tensor.reshape(-1, self.Ks * c_in), self.weight.reshape(self.Ks * c_in, -1)).reshape(-1, self.c_out)

        if self.bias is not None:
            x_chebconv = x_mul + self.bias
        else:
            x_chebconv = x_mul
        
        return x_chebconv

class GCNConv(nn.Module): #√
    def __init__(self, c_in, c_out, gcnconv_matrix, enable_bias, graph_conv_act_func):
        super(GCNConv, self).__init__()
        self.c_in = c_in
        self.c_out = c_out
        self.gcnconv_matrix = gcnconv_matrix
        self.enable_bias = enable_bias
        self.graph_conv_act_func = graph_conv_act_func
        self.weight = nn.Parameter(torch.FloatTensor(self.c_in, self.c_out))
        if enable_bias == True:
            self.bias = nn.Parameter(torch.FloatTensor(self.c_out))
        else:
            self.register_parameter('bias', None)
        self.initialize_parameters()

    def initialize_parameters(self): 
        # print("OliviaO")
        # For Sigmoid, Tanh or Softsign
        if self.graph_conv_act_func == 'sigmoid' or self.graph_conv_act_func == 'tanh' or self.graph_conv_act_func == 'softsign':
            init.xavier_uniform_(self.weight)

        # For ReLU, Softplus, Leaky ReLU, PReLU, or ELU
        elif self.graph_conv_act_func == 'relu' or self.graph_conv_act_func == 'softplus' or self.graph_conv_act_func == 'leakyrelu' \
            or self.graph_conv_act_func == 'prelu' or self.graph_conv_act_func == 'elu':
            init.kaiming_uniform_(self.weight)

        if self.bias is not None:
            _out_feats_bias = self.bias.size(0)
            stdv_b = 1. / math.sqrt(_out_feats_bias)
            init.uniform_(self.bias, -stdv_b, stdv_b)

    def forward(self, x):
        batch_size, c_in, T, n_vertex = x.shape

        x_first_mul = torch.mm(x.reshape(-1, c_in), self.weight).reshape(n_vertex, -1)
        x_second_mul = torch.mm(self.gcnconv_matrix, x_first_mul).reshape(-1, self.c_out)

        if self.bias is not None:
            x_gcnconv_out = x_second_mul + self.bias
        else:
            x_gcnconv_out = x_second_mul
        
        return x_gcnconv_out

class GraphConvLayer(nn.Module): #√
    def __init__(self, Ks, c_in, c_out, graph_conv_type, graph_conv_matrix, graph_conv_act_func):#graph_conv_act_func为search_space的"act"
        super(GraphConvLayer, self).__init__()
        self.Ks = Ks
        self.c_in = c_in
        self.c_out = c_out
        self.align = Align(self.c_in, self.c_out)
        self.graph_conv_type = graph_conv_type
        self.graph_conv_matrix = graph_conv_matrix
        self.graph_conv_act_func = graph_conv_act_func
        self.enable_bias = True

        # 区别
        if (self.graph_conv_type == "chebconv"):
            self.chebconv = ChebConv(self.c_out, self.c_out, self.Ks, self.graph_conv_matrix, self.enable_bias, self.graph_conv_act_func)
            #(self, c_in, c_out, Ks, chebconv_matrix, enable_bias, graph_conv_act_func)
        elif (self.graph_conv_type == "gcnconv"):
            self.gcnconv = GCNConv(self.c_out, self.c_out, self.graph_conv_matrix, self.enable_bias, self.graph_conv_act_func)

    def forward(self, x): 
        x_gc_in = self.align(x)
        batch_size, c_in, T, n_vertex = x_gc_in.shape
        if (self.graph_conv_type == "chebconv"):
            x_gc = self.chebconv(x_gc_in)
        elif (self.graph_conv_type == "gcnconv"):
            x_gc = self.gcnconv(x_gc_in)
        x_gc_with_rc = torch.add(x_gc.reshape(batch_size, self.c_out, T, n_vertex), x_gc_in)
        x_gc_out = x_gc_with_rc
        return x_gc_out

class STConvBlock(nn.Module): #√
    # STConv Block contains 'TNSATND' structure
    # T: Gated Temporal Convolution Layer (GLU or GTU)
    # G: Graph Convolution Layer (ChebConv or GCNConv)
    # T: Gated Temporal Convolution Layer (GLU or GTU)
    # N: Layer Normolization
    # D: Dropout

    def __init__(self, Kt, Ks, n_vertex, last_block_channel, channels, gated_act_func, graph_conv_type, conv_matrix, drop_rate, ratio, act): 
        super(STConvBlock, self).__init__()
        self.Kt = Kt
        self.Ks = Ks
        self.n_vertex = n_vertex
        self.last_block_channel = last_block_channel
        self.channels = channels
        self.gated_act_func = gated_act_func #glu/gtu
        self.enable_gated_act_func = True
        self.graph_conv_type = graph_conv_type
        self.graph_conv_matrix = conv_matrix
        self.graph_conv_act_func = 'relu' #👀
        self.drop_rate = drop_rate
        self.ratio = ratio
        self.tmp_conv1 = TemporalConvLayer(self.Kt, self.last_block_channel, self.channels[0], self.n_vertex, self.gated_act_func, self.enable_gated_act_func, self.ratio) #+2

        self.graph_conv = GraphConvLayer(self.Ks, self.channels[0], self.channels[1], self.graph_conv_type, self.graph_conv_matrix, self.graph_conv_act_func) 
        
        self.tmp_conv2 = TemporalConvLayer(self.Kt, self.channels[1], self.channels[2], self.n_vertex, self.gated_act_func, self.enable_gated_act_func, self.ratio) #+2
        self.tc2_ln = nn.LayerNorm([self.n_vertex, self.channels[2]])
        self.sigmoid = nn.Sigmoid()
        self.tanh = nn.Tanh()
        self.relu = nn.ReLU()
        self.softplus = nn.Softplus()
        self.leakyrelu = nn.LeakyReLU()
        self.prelu = nn.PReLU()
        self.elu = nn.ELU()
        self.do = nn.Dropout(p=self.drop_rate)

    def forward(self, x): 
        x_tmp_conv1 = self.tmp_conv1(x)
        x_graph_conv = self.graph_conv(x_tmp_conv1)
        x_act_func = act_map(self.graph_conv_act_func)(x_graph_conv)
        x_tmp_conv2 = self.tmp_conv2(x_act_func)
        x_tc2_ln = self.tc2_ln(x_tmp_conv2.permute(0, 2, 3, 1)).permute(0, 3, 1, 2)
        x_do = self.do(x_tc2_ln)
        x_st_conv_out = x_do
        return x_st_conv_out

class OutputBlock(nn.Module): #√
    # Output block contains 'TNFF' structure
    # T: Gated Temporal Convolution Layer (GLU or GTU)
    # N: Layer Normolization
    # F: Fully-Connected Layer
    # F: Fully-Connected Layer

    def __init__(self, Ko, last_block_channel, channels, end_channel, n_vertex, gated_act_func, drop_rate, ratio): 
        super(OutputBlock, self).__init__()
        self.Ko = Ko
        self.last_block_channel = last_block_channel
        self.channels = channels
        self.end_channel = end_channel
        self.n_vertex = n_vertex
        self.gated_act_func = gated_act_func
        self.enable_gated_act_func = True
        self.drop_rate = drop_rate
        self.ratio = ratio
        self.tmp_conv1 = TemporalConvLayer(self.Ko, self.last_block_channel, self.channels[0], self.n_vertex, self.gated_act_func, self.enable_gated_act_func, self.ratio) 
        #(self, Kt, c_in, c_out, n_vertex, gated_act_func, enable_gated_act_func, ratio)
        self.fc1 = nn.Linear(self.channels[0], self.channels[1])
        self.fc2 = nn.Linear(self.channels[1], self.end_channel)
        self.tc1_ln = nn.LayerNorm([self.n_vertex, self.channels[0]])
        self.act_func = 'sigmoid'
        self.sigmoid = nn.Sigmoid()
        self.tanh = nn.Tanh()
        self.softsign = nn.Softsign()
        self.relu = nn.ReLU()
        self.softplus = nn.Softplus()
        self.leakyrelu = nn.LeakyReLU()
        self.prelu = nn.PReLU()
        self.elu = nn.ELU()
        self.do = nn.Dropout(p=self.drop_rate)

    def forward(self, x): 
        x_tc1 = self.tmp_conv1(x)
        x_tc1_ln = self.tc1_ln(x_tc1.permute(0, 2, 3, 1))
        x_fc1 = self.fc1(x_tc1_ln)
        x_act_func = act_map(self.act_func)(x_fc1)
        x_fc2 = self.fc2(x_act_func).permute(0, 3, 1, 2)
        x_out = x_fc2
        return x_out




