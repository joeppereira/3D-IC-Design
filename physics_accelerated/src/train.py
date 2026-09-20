import json
import sys
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

    # --- physics-informed term (PINO) --------------------------------------
    # An FNO is an architecture; "physics-informed" is a property of the loss.
    # Adding the discrete heat-equation residual makes this a physics-informed
    # neural operator: the network is penalised for predicting fields that are
    # not solutions, independently of whether the labels are any good.
    # Always construct it: the residual is a *metric* as well as a loss term, so
    # the plain-MSE baseline must be measured the same way or the comparison is
    # meaningless.
    lam = float(args.lambda_physics)
    if True:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        '..', '..', 'serdes_architect', 'src'))
        from heat_residual import HeatEquationResidual
        from thermal.solver import ThermalSolver
        solver_cfg = args.config
        residual_op = HeatEquationResidual.from_solver(
            ThermalSolver(solver_cfg)).to(device)
        print(f"  Physics term: lambda = {lam:g}"
              f"{' (metric only, not in the loss)' if lam == 0 else ''}")
        with torch.no_grad():
            lab_res = residual_op.rms_k(y_train, x_train)
        print(f"  Heat-equation residual of the TRAINING LABELS: {lab_res:.3e} K "
              f"({'labels are converged' if lab_res < 1e-3 else 'LABELS ARE NOT CONVERGED'})")
    
    # Training Loop
    t0 = time.time()
    for epoch in range(args.epochs):
        model.train()
        train_loss = 0
        epoch_phys = 0.0
        for x, y in train_loader:
            optimizer.zero_grad()
            out = model(x)
            
            # Weighted Loss?
            if args.weighted_loss:
                # Weight hotspots more (regions where T > 1.0 sigma)
                weight_map = torch.where(y > 1.0, 5.0, 1.0)
                data_loss = (weight_map * (out - y)**2).mean()
            else:
                data_loss = criterion(out, y)

            loss = data_loss
            # De-normalise to physical temperature before applying the PDE.
            t_phys = out * y_std + y_mean
            r = residual_op(t_phys, x)              # kelvin
            phys_term = (r ** 2).mean()
            epoch_phys += float(torch.sqrt(phys_term.detach()))
            if lam > 0.0:
                loss = loss + lam * phys_term

            loss.backward()
            optimizer.step()
            train_loss += loss.item()
            
        scheduler.step()
        
        if epoch % 5 == 0 or epoch == args.epochs - 1:
            msg = (f"  Epoch {epoch}/{args.epochs} | Loss: "
                   f"{train_loss/len(train_loader):.6f} | LR: "
                   f"{scheduler.get_last_lr()[0]:.1e}")
            msg += f" | physics residual: {epoch_phys/len(train_loader):.4e} K"
            print(msg)

    print(f"✅ Training Complete in {time.time() - t0:.2f}s")
    
    # Save Model
    os.makedirs('results', exist_ok=True)
    torch.save(model.state_dict(), 'results/fno_model.pt')
    
    # --- final physics audit ----------------------------------------------
    model.eval()
    metrics = {}
    with torch.no_grad():
        pred = model(x_train) * y_std + y_mean
        err = pred - y_train
        metrics = {
            "data_rmse_k": float(torch.sqrt((err ** 2).mean())),
            "data_max_abs_k": float(err.abs().max()),
            "label_peak_c": float(y_train.max()),
            "pred_peak_c": float(pred.max()),
            "peak_error_k": float(pred.max() - y_train.max()),
            "lambda_physics": float(args.lambda_physics),
            "epochs": int(args.epochs),
            "samples": int(x_train.shape[0]),
        }
        metrics["pred_residual_k"] = residual_op.rms_k(pred, x_train)
        metrics["label_residual_k"] = residual_op.rms_k(y_train, x_train)
    print(f"  Data RMSE: {metrics['data_rmse_k']:.4f} K | peak error: "
          f"{metrics['peak_error_k']:+.4f} K")
    if "pred_residual_k" in metrics:
        print(f"  Heat-equation residual -- prediction: "
              f"{metrics['pred_residual_k']:.4e} K, labels: "
              f"{metrics['label_residual_k']:.4e} K")

    # Save Normalization Stats for Inference
    stats = {'mean': y_mean.item(), 'std': y_std.item()}
    torch.save(stats, 'results/norm_stats.pt')
    suffix = f"_lam{args.lambda_physics:g}".replace(".", "p")
    torch.save(model.state_dict(), f'results/fno_model{suffix}.pt')
    with open(f'results/train_metrics{suffix}.json', 'w') as fh:
        json.dump(metrics, fh, indent=2)
    print(f"  Saved model, stats and metrics to results/ (variant {suffix})")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--epochs', type=int, default=30, help='Training epochs')
    parser.add_argument('--weighted_loss', type=str, default='false', help='Use hotspot weighting')
    parser.add_argument('--in_channels', type=int, default=5, help='Number of input channels')
    parser.add_argument('--lambda_physics', type=float, default=0.0,
                        help='Weight on the heat-equation residual (0 = plain MSE)')
    parser.add_argument('--config', type=str,
                        default='results/golden_config.json',
                        help='Config supplying geometry/materials for the residual')
    args = parser.parse_args()
    
    # Fix boolean parsing
    if args.weighted_loss.lower() == 'true':
        args.weighted_loss = True
    else:
        args.weighted_loss = False
        
    train(args)
