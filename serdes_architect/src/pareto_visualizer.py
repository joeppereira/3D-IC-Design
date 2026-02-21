import pandas as pd
import plotly.express as px
import argparse
import os

def visualize_pareto(csv_path, output_html):
    print(f"📊 Generating Enhanced Pareto Visualization from {csv_path}...")
    
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"❌ Failed to read CSV: {e}")
        return

    # Create Parallel Coordinates Plot with distinct colors for Package Type
    # Mapping package types to numeric values for coloring
    df['pkg_id'] = df['package_type'].astype('category').cat.codes
    
    fig = px.parallel_coordinates(
        df, 
        color="pkg_id",
        dimensions=[
            "relative_cost",
            "power_efficiency_pjb",
            "die_area_mm2",
            "thermal_tj_c",
            "link_eye_margin_ui"
        ],
        labels={
            "relative_cost": "Cost (Rel)",
            "power_efficiency_pjb": "Power (pJ/b)",
            "die_area_mm2": "Area (mm²)",
            "thermal_tj_c": "Temp (°C)",
            "link_eye_margin_ui": "Eye Margin (UI)"
        },
        color_continuous_scale=px.colors.qualitative.Plotly,
        title="3D IC Designer: Multi-Objective Pareto Surface (V2.0 Calibrated)"
    )
    
    # Identify Champions
    power_opt = df.loc[df['power_efficiency_pjb'].idxmin()]
    perf_opt = df.loc[df['link_eye_margin_ui'].idxmax()]
    # Density heuristic: small area + high speed
    density_opt = df.loc[(df['die_area_mm2'] / (df['power_efficiency_pjb'] + 0.1)).idxmin()]

    # Generate Summary HTML
    summary_html = f"""
    <div style="font-family: sans-serif; padding: 20px; background: #f4f4f9; border-radius: 10px; margin-top: 20px;">
        <h2 style="color: #2c3e50;">🏆 Architectural Selection Summary</h2>
        <table style="width: 100%; border-collapse: collapse;">
            <tr style="background: #34495e; color: white;">
                <th style="padding: 10px; text-align: left;">Category</th>
                <th style="padding: 10px; text-align: left;">Selected Design</th>
                <th style="padding: 10px; text-align: left;">Package / Interposer</th>
                <th style="padding: 10px; text-align: left;">Key Metric</th>
            </tr>
            <tr>
                <td style="padding: 10px; border-bottom: 1px solid #ddd;"><b>Power Optimized</b></td>
                <td style="padding: 10px; border-bottom: 1px solid #ddd;">{power_opt['design_name']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #ddd;">{power_opt['package_type']} / {power_opt['interposer']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #ddd;">{power_opt['power_efficiency_pjb']} pJ/b</td>
            </tr>
            <tr style="background: #fff;">
                <td style="padding: 10px; border-bottom: 1px solid #ddd;"><b>Performance Optimized</b></td>
                <td style="padding: 10px; border-bottom: 1px solid #ddd;">{perf_opt['design_name']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #ddd;">{perf_opt['package_type']} / {perf_opt['interposer']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #ddd;">{perf_opt['link_eye_margin_ui']} UI Margin</td>
            </tr>
            <tr>
                <td style="padding: 10px; border-bottom: 1px solid #ddd;"><b>Density Optimized</b></td>
                <td style="padding: 10px; border-bottom: 1px solid #ddd;">{density_opt['design_name']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #ddd;">{density_opt['package_type']} / {density_opt['interposer']}</td>
                <td style="padding: 10px; border-bottom: 1px solid #ddd;">{density_opt['die_area_mm2']} mm²</td>
            </tr>
        </table>
        <div style="margin-top: 20px; font-size: 0.9em; color: #7f8c8d;">
            <i>Note: "Performance Optimized" chooses maximum SNR headroom for 224G/112G reliability. "Power Optimized" favors XSR/UCIe links with minimal EQ.</i>
        </div>
    </div>
    """

    os.makedirs(os.path.dirname(output_html), exist_ok=True)
    
    # Save Plotly HTML
    plot_html = fig.to_html(full_html=False, include_plotlyjs='cdn')
    
    with open(output_html, "w") as f:
        f.write("<html><body>")
        f.write(plot_html)
        f.write(summary_html)
        f.write("</body></html>")
        
    print(f"✅ Enhanced Dashboard saved to {output_html}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', type=str, default='reports/pareto_data.csv')
    parser.add_argument('--out', type=str, default='reports/pareto_dashboard.html')
    args = parser.parse_args()
    
    visualize_pareto(args.csv, args.out)