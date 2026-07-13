#!/usr/bin/env python3
"""Plot training losses and performance metrics for all channels."""

import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from matplotlib.ticker import LogLocator
import numpy as np
import pickle
from sklearn.metrics import roc_curve, auc

# Base directory for results
base_dir = Path("/work/sgiappic/smhtt_ul/trainings/uncertainty-aware-training/routine_output/CENNTExperiments")

# Channels to plot with LaTeX names
channels = ["et", "mt", "tt"]
channel_names = {
    "et": r"$e\tau$",
    "mt": r"$\mu\tau$",
    "tt": r"$\tau\tau$"
}
version = "260507_v3"

# Create figure with subplots for each channel and fold
fig, axes = plt.subplots(2, 3, figsize=(18, 12))
fig.suptitle("Training Losses by Channel", fontsize=16, fontweight='bold')

folds = ["fold0", "fold1"]

for fold_idx, fold in enumerate(folds):
    for channel_idx, channel in enumerate(channels):
        ax = axes[fold_idx, channel_idx]
        
        # Construct path to losses.feather file
        pattern = f"CENNTTraining_{version}_{channel}/SMHtt__{fold}/*/0_*"
        matching_dirs = list(base_dir.glob(pattern))
        
        if not matching_dirs:
            print(f"Warning: No matching directory for channel {channel}, {fold}")
            continue
        
        # Get the first matching directory (or most recent)
        loss_file = matching_dirs[0] / "losses" / "losses.feather"
        
        if not loss_file.exists():
            print(f"Warning: File not found: {loss_file}")
            continue
        
        # Read losses
        df = pd.read_feather(loss_file)
        
        # Plot training and validation loss
        if "('Train', 'CE', '')" in df.columns and "('Validation', 'CE', '')" in df.columns:
            ax.plot(df.loc[:, "('Train', 'CE', '')"], label="Training", linewidth=2, color="#89ab7c")
            ax.plot(df.loc[:, "('Validation', 'CE', '')"], label="Validation", linewidth=2, color="#6b6ca3")
        else:
            print(f"Warning: Expected loss columns not found for {channel}")
            print(f"Available columns: {list(df.columns)}")
            continue
        
        ax.set_xlabel("Epoch", fontsize=15)
        ax.set_ylabel("Cross Entropy Loss", fontsize=15)
        ax.set_yscale("log")
        ax.yaxis.set_minor_locator(LogLocator(base=10.0, subs=range(1, 50)))
        ax.legend(title=f"Channel: {channel_names[channel]} ({fold})", fontsize=15, title_fontsize=15)
        ax.tick_params(axis='both', labelsize=12)
        ax.grid(True, alpha=0.3, which='both')

plt.tight_layout(rect=[0, 0, 1, 0.95])
plt.savefig("losses_plot.png", dpi=330, bbox_inches='tight')
plt.savefig("losses_plot.pdf", bbox_inches='tight')
print("Plot saved to losses_plot.png")

# Plot residuals distributions and ROC curves
fig, axes = plt.subplots(2, 3, figsize=(18, 12))
fig.suptitle("Residuals Distributions by Channel", fontsize=16, fontweight='bold')

for fold_idx, fold in enumerate(folds):
    for channel_idx, channel in enumerate(channels):
        ax = axes[fold_idx, channel_idx]
        
        # Construct path to histogram data
        pattern = f"CENNTTraining_{version}_{channel}/SMHtt__{fold}/*/0_*"
        matching_dirs = list(base_dir.glob(pattern))
        
        if not matching_dirs:
            print(f"Warning: No matching directory for channel {channel}, {fold}")
            continue
        
        data_file = matching_dirs[0] / "nn_output" / "data" / "all_hist_data.pickle"
        
        if not data_file.exists():
            print(f"Warning: File not found: {data_file}")
            continue
        
        try:
            with open(data_file, 'rb') as f:
                hist_data = pickle.load(f)
            
            # Extract data and predictions
            data_obs = np.array(hist_data['data_obs'].values[0])
            sig0 = np.array(hist_data['sig0'].values[0])
            bkg_total = np.array(hist_data['bkg0'].values[0]) + np.array(hist_data['bkg1'].values[0]) + \
                       np.array(hist_data['bkg2'].values[0]) + np.array(hist_data['bkg3'].values[0]) + \
                       np.array(hist_data['bkg4'].values[0])
            
            # Calculate residuals: (observed - predicted) / sqrt(observed + 1e-10 to avoid division by zero)
            predicted_total = sig0 + bkg_total
            residuals = (data_obs - predicted_total) / np.sqrt(np.abs(data_obs) + 1e-10)
            
            # Plot residuals distribution
            ax.hist(residuals, bins=30, color="#89ab7c", alpha=0.7, edgecolor='black')
            ax.axvline(0, color='red', linestyle='--', linewidth=2, label='Perfect prediction')
            ax.set_xlabel("Residuals (σ)", fontsize=12)
            ax.set_ylabel("Frequency", fontsize=12)
            ax.set_title(f"Channel: {channel_names[channel]} ({fold})", fontsize=12, fontweight='bold')
            ax.legend(fontsize=10)
            ax.grid(True, alpha=0.3)
            
        except Exception as e:
            ax.text(0.5, 0.5, f"Error: {str(e)[:40]}", ha='center', va='center', 
                   transform=ax.transAxes, fontsize=10)
            ax.axis('off')

plt.tight_layout(rect=[0, 0, 1, 0.95])
plt.savefig("residuals_plot.png", dpi=330, bbox_inches='tight')
plt.savefig("residuals_plot.pdf", bbox_inches='tight')
print("Plot saved to residuals_plot.png")

# Plot ROC curves
fig, axes = plt.subplots(2, 3, figsize=(18, 12))
fig.suptitle("ROC Curves: Signal vs Background by Channel", fontsize=16, fontweight='bold')

for fold_idx, fold in enumerate(folds):
    for channel_idx, channel in enumerate(channels):
        ax = axes[fold_idx, channel_idx]
        
        # Construct path to histogram data
        pattern = f"CENNTTraining_{version}_{channel}/SMHtt__{fold}/*/0_*"
        matching_dirs = list(base_dir.glob(pattern))
        
        if not matching_dirs:
            continue
        
        data_file = matching_dirs[0] / "nn_output" / "data" / "all_hist_data.pickle"
        
        if not data_file.exists():
            continue
        
        try:
            with open(data_file, 'rb') as f:
                hist_data = pickle.load(f)
            
            # Extract signal and background
            sig0 = np.array(hist_data['sig0'].values[0])
            bkg_total = np.array(hist_data['bkg0'].values[0]) + np.array(hist_data['bkg1'].values[0]) + \
                       np.array(hist_data['bkg2'].values[0]) + np.array(hist_data['bkg3'].values[0]) + \
                       np.array(hist_data['bkg4'].values[0])
            
            # Create binary labels: 1 for signal, 0 for background
            y_true = np.concatenate([np.ones(len(sig0)), np.zeros(len(bkg_total))])
            y_score = np.concatenate([sig0, bkg_total])
            
            # Calculate ROC curve
            fpr, tpr, _ = roc_curve(y_true, y_score)
            roc_auc = auc(fpr, tpr)
            
            # Plot ROC curve
            ax.plot(fpr, tpr, color="#6b6ca3", linewidth=2.5, label=f'ROC (AUC = {roc_auc:.3f})')
            ax.plot([0, 1], [0, 1], 'k--', linewidth=1, alpha=0.5, label='Random classifier')
            ax.set_xlabel("False Positive Rate", fontsize=12)
            ax.set_ylabel("True Positive Rate", fontsize=12)
            ax.set_title(f"Channel: {channel_names[channel]} ({fold})", fontsize=12, fontweight='bold')
            ax.legend(fontsize=11, loc='lower right')
            ax.grid(True, alpha=0.3)
            ax.set_xlim([0, 1])
            ax.set_ylim([0, 1])
            
        except Exception as e:
            ax.text(0.5, 0.5, f"Error: {str(e)[:40]}", ha='center', va='center', 
                   transform=ax.transAxes, fontsize=10)
            ax.axis('off')

plt.tight_layout(rect=[0, 0, 1, 0.95])
plt.savefig("roc_plot.png", dpi=330, bbox_inches='tight')
plt.savefig("roc_plot.pdf", bbox_inches='tight')
print("Plot saved to roc_plot.png")
