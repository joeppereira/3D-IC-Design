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
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 20px; background: #ffffff; border: 1px solid #dfe6e9; border-radius: 8px; margin-top: 30px;">
        <h2 style="color: #2d3436; border-bottom: 2px solid #0984e3; padding-bottom: 10px;">Architectural Selection Summary</h2>
        <table style="width: 100%; border-collapse: collapse; margin-top: 15px;">
            <tr style="background: #f1f2f6; color: #2d3436; font-weight: bold;">
                <th style="padding: 12px; text-align: left; border-bottom: 2px solid #dfe6e9;">Category</th>
                <th style="padding: 12px; text-align: left; border-bottom: 2px solid #dfe6e9;">Design ID</th>
                <th style="padding: 12px; text-align: left; border-bottom: 2px solid #dfe6e9;">Package Topology</th>
                <th style="padding: 12px; text-align: left; border-bottom: 2px solid #dfe6e9;">Area (mm²)</th>
                <th style="padding: 12px; text-align: left; border-bottom: 2px solid #dfe6e9;">Efficiency (pJ/b)</th>
                <th style="padding: 12px; text-align: left; border-bottom: 2px solid #dfe6e9;">Margin (UI)</th>
            </tr>
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9;"><b>Power Champion</b></td>
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9;">{power_opt['design_name']}</td>
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9;">{power_opt['package_type']}</td>
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9;">{power_opt['die_area_mm2']}</td>
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9; color: #00b894;"><b>{power_opt['power_efficiency_pjb']}</b></td>
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9;">{power_opt['link_eye_margin_ui']}</td>
            </tr>
            <tr style="background: #f9f9f9;">
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9;"><b>Performance Champion</b></td>
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9;">{perf_opt['design_name']}</td>
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9;">{perf_opt['package_type']}</td>
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9;">{perf_opt['die_area_mm2']}</td>
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9;">{perf_opt['power_efficiency_pjb']}</td>
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9; color: #0984e3;"><b>{perf_opt['link_eye_margin_ui']}</b></td>
            </tr>
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9;"><b>Density Champion</b></td>
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9;">{density_opt['design_name']}</td>
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9;">{density_opt['package_type']}</td>
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9; color: #d63031;"><b>{density_opt['die_area_mm2']}</b></td>
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9;">{density_opt['power_efficiency_pjb']}</td>
                <td style="padding: 12px; border-bottom: 1px solid #dfe6e9;">{density_opt['link_eye_margin_ui']}</td>
            </tr>
        </table>
        <div style="margin-top: 15px; font-size: 0.85em; color: #636e72;">
            <i>Calibration Note: Performance metrics based on 112GHz Nyquist scaling. Area inclusive of SerDes beachfront and Logic Core.</i>
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