import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
import argparse
import os
import time

# --- FNO Building Blocks ---

class SpectralConv2d(nn.Module):
    def __init__(self, in_channels, out_channels, modes1, modes2):
        super(SpectralConv2d, self).__init__()
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.modes1 = modes1 # Number of Fourier modes to multiply, at most floor(N/2) + 1
        self.modes2 = modes2

        self.scale = (1 / (in_channels * out_channels))
        self.weights1 = nn.Parameter(self.scale * torch.rand(in_channels, out_channels, self.modes1, self.modes2, dtype=torch.cfloat))
        self.weights2 = nn.Parameter(self.scale * torch.rand(in_channels, out_channels, self.modes1, self.modes2, dtype=torch.cfloat))

    def compl_mul2d(self, input, weights):
        # (batch, in_channel, x, y), (in_channel, out_channel, x, y) -> (batch, out_channel, x, y)
        return torch.einsum("bixy,ioxy->boxy", input, weights)

    def forward(self, x):
        batchsize = x.shape[0]
        # Compute Fourier coeffcients up to a factor of e^(- something constant)
        x_ft = torch.fft.rfft2(x)

        # Multiply relevant Fourier modes
        out_ft = torch.zeros(batchsize, self.out_channels, x.size(-2), x.size(-1)//2 + 1, dtype=torch.cfloat, device=x.device)
        
        # Upper block (modes1, modes2)
        out_ft[:, :, :self.modes1, :self.modes2] = \
            self.compl_mul2d(x_ft[:, :, :self.modes1, :self.modes2], self.weights1)
            
        # Lower block (modes1, modes2)
        out_ft[:, :, -self.modes1:, :self.modes2] = \
            self.compl_mul2d(x_ft[:, :, -self.modes1:, :self.modes2], self.weights2)

        # Return to physical space
        x = torch.fft.irfft2(out_ft, s=(x.size(-2), x.size(-1)))
        return x

class FNO2d(nn.Module):
    def __init__(self, modes1, modes2, width, layers=5):
        super(FNO2d, self).__init__()
        self.modes1 = modes1
        self.modes2 = modes2
        self.width = width
        self.layers = layers
        
        # Input Channel (Power) -> High Dim Feature
        self.fc0 = nn.Linear(layers + 2, width) # +2 for Grid coordinates (x,y)

        self.conv0 = SpectralConv2d(width, width, modes1, modes2)
        self.conv1 = SpectralConv2d(width, width, modes1, modes2)
        self.conv2 = SpectralConv2d(width, width, modes1, modes2)
        self.conv3 = SpectralConv2d(width, width, modes1, modes2)
        
        self.w0 = nn.Conv2d(width, width, 1)
        self.w1 = nn.Conv2d(width, width, 1)
        self.w2 = nn.Conv2d(width, width, 1)
        self.w3 = nn.Conv2d(width, width, 1)

        # High Dim Feature -> Output Channel (Temperature)
        self.fc1 = nn.Linear(width, 128)
        self.fc2 = nn.Linear(128, layers)

    def get_grid(self, shape, device):
        batchsize, size_x, size_y = shape[0], shape[2], shape[3]
        gridx = torch.tensor(torch.linspace(0, 1, size_x), dtype=torch.float)
        gridx = gridx.reshape(1, 1, size_x, 1).repeat([batchsize, 1, 1, size_y])
        gridy = torch.tensor(torch.linspace(0, 1, size_y), dtype=torch.float)
        gridy = gridy.reshape(1, 1, 1, size_y).repeat([batchsize, 1, size_x, 1])
        return torch.cat((gridx, gridy), dim=1).to(device)

    def forward(self, x):
        grid = self.get_grid(x.shape, x.device)
        x = torch.cat((x, grid), dim=1)
        
        # (Batch, Channels, X, Y) -> (Batch, X, Y, Channels) for Linear
        x = x.permute(0, 2, 3, 1)
        x = self.fc0(x)
        x = x.permute(0, 3, 1, 2)

        x1 = self.conv0(x)
        x2 = self.w0(x)
        x = x1 + x2
        x = F.gelu(x)

        x1 = self.conv1(x)
        x2 = self.w1(x)
        x = x1 + x2
        x = F.gelu(x)

        x1 = self.conv2(x)
        x2 = self.w2(x)
        x = x1 + x2
        x = F.gelu(x)

        x1 = self.conv3(x)
        x2 = self.w3(x)
        x = x1 + x2

        # (Batch, Channels, X, Y) -> (Batch, X, Y, Channels)
        x = x.permute(0, 2, 3, 1)
        x = self.fc1(x)
        x = F.gelu(x)
        x = self.fc2(x)
        
        # Return to (Batch, Channels, X, Y)
        return x.permute(0, 3, 1, 2)

# --- Training Logic ---

def train(args):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"🚀 Training FNO Surrogate on {device}...")
    
    # Load Data
    data_dir = 'data'
    print(f"DEBUG: CWD is {os.getcwd()}")
    print(f"DEBUG: Checking {os.path.abspath(data_dir)}")
    if os.path.exists(data_dir):
        print(f"DEBUG: Contents of {data_dir}: {os.listdir(data_dir)}")
    else:
        print(f"DEBUG: {data_dir} does not exist!")

    try:
        x_train = torch.load(os.path.join(data_dir, 'x_physics.pt')).to(device)
        y_train = torch.load(os.path.join(data_dir, 'y_spatial.pt')).to(device)
    except FileNotFoundError:
        print("❌ Data not found! Please run Phase 1 (serdes_architect) first.")
        return

    # Normalize Data (Simple Min-Max or Z-score is recommended, but for now we trust the raw values are reasonable)
    # Ideally: y_train = (y_train - mean) / std
    y_mean = y_train.mean()
    y_std = y_train.std()
    y_train_norm = (y_train - y_mean) / y_std
    
    # Dataset
    train_dataset = TensorDataset(x_train, y_train_norm)
    train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
    
    # Model
    # modes=8, width=32 is a small model for demo speed. Increase for production.
    model = FNO2d(modes1=8, modes2=8, width=32, layers=x_train.shape[1]).to(device)
    
    optimizer = optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=10, gamma=0.5)
    
    criterion = nn.MSELoss()
    
    # Training Loop
    t0 = time.time()
    for epoch in range(args.epochs):
        model.train()
        train_loss = 0
        for x, y in train_loader:
            optimizer.zero_grad()
            out = model(x)
            
            # Weighted Loss?
            if args.weighted_loss:
                # Weight hotspots more (regions where T > 1.0 sigma)
                weight_map = torch.where(y > 1.0, 5.0, 1.0)
                loss = (weight_map * (out - y)**2).mean()
            else:
                loss = criterion(out, y)
                
            loss.backward()
            optimizer.step()
            train_loss += loss.item()
            
        scheduler.step()
        
        if epoch % 5 == 0:
            print(f"  Epoch {epoch}/{args.epochs} | Loss: {train_loss/len(train_loader):.6f} | LR: {scheduler.get_last_lr()[0]:.1e}")

    print(f"✅ Training Complete in {time.time() - t0:.2f}s")
    
    # Save Model
    os.makedirs('results', exist_ok=True)
    torch.save(model.state_dict(), 'results/fno_model.pt')
    
    # Save Normalization Stats for Inference
    stats = {'mean': y_mean.item(), 'std': y_std.item()}
    torch.save(stats, 'results/norm_stats.pt')
    print("  Saved model and stats to results/")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--epochs', type=int, default=30, help='Training epochs')
    parser.add_argument('--weighted_loss', type=str, default='false', help='Use hotspot weighting')
    parser.add_argument('--in_channels', type=int, default=5, help='Number of input channels')
    args = parser.parse_args()
    
    # Fix boolean parsing
    if args.weighted_loss.lower() == 'true':
        args.weighted_loss = True
    else:
        args.weighted_loss = False
        
    train(args)
