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

    # Create Group ID for coloring (1: CoWoS, 2: 3D Hetero, etc.)
    def get_group_id(name):
        if "CoWoS" in name: return 1
        if "3D_Hetero" in name: return 2
        if "SoP" in name: return 3
        if "CPO" in name: return 4
        if "Wafer_Scale" in name: return 5
        return 0

    df['group_id'] = df['design_name'].apply(get_group_id)
    
    # Parallel Coordinates Plot
    fig = px.parallel_coordinates(
        df, 
        color="group_id",
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
        color_continuous_scale=[
            (0.00, "grey"),   (0.2, "blue"),   # CoWoS
            (0.2, "blue"),   (0.4, "green"),  # 3D Hetero
            (0.4, "green"),  (0.6, "orange"), # SoP
            (0.6, "orange"), (0.8, "red"),    # CPO
            (0.8, "red"),    (1.0, "purple")  # Wafer Scale
        ],
        title="3D IC Designer: Multi-Objective Pareto Surface (V2.0 Calibrated)"
    )
    
    # Identify Champions (Filtering for Eye > 0)
    valid_df = df[df['link_eye_margin_ui'] > 0.01]
    if valid_df.empty: valid_df = df # Fallback if all 0
    
    power_opt = valid_df.loc[valid_df['power_efficiency_pjb'].idxmin()]
    perf_opt = valid_df.loc[valid_df['link_eye_margin_ui'].idxmax()]
    density_opt = valid_df.loc[(valid_df['die_area_mm2'] / (valid_df['power_efficiency_pjb'] + 0.1)).idxmin()]

    # Architecture Key Table
    key_html = """
    <div style="margin-top: 20px; font-family: sans-serif; display: flex; gap: 20px;">
        <div style="flex: 1; padding: 15px; background: #f8f9fa; border-radius: 8px;">
            <h3 style="margin-top:0;">🎨 Color Key</h3>
            <ul style="list-style: none; padding: 0;">
                <li><span style="color:blue;">■</span> <b>Blue:</b> 2.5D CoWoS (Cost Focused)</li>
                <li><span style="color:green;">■</span> <b>Green:</b> 3D Heterogeneous (Z-Power)</li>
                <li><span style="color:orange;">■</span> <b>Orange:</b> 3D SoP (Thermal Specialized)</li>
                <li><span style="color:red;">■</span> <b>Red:</b> Co-Packaged Optics (Reach Kings)</li>
                <li><span style="color:purple;">■</span> <b>Purple:</b> Wafer-Scale Integration</li>
            </ul>
        </div>
    """

    # Selection Summary Table
    summary_html = f"""
        <div style="flex: 2; padding: 15px; background: #ffffff; border: 1px solid #dfe6e9; border-radius: 8px;">
            <h3 style="margin-top:0;">🏆 Architectural Selection Summary</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="background: #f1f2f6;">
                    <th style="padding: 8px; text-align: left;">Champion</th>
                    <th style="padding: 8px; text-align: left;">Design</th>
                    <th style="padding: 8px; text-align: left;">Area</th>
                    <th style="padding: 8px; text-align: left;">pJ/b</th>
                    <th style="padding: 8px; text-align: left;">Margin</th>
                </tr>
                <tr>
                    <td><b>Power</b></td>
                    <td>{power_opt['design_name']}</td>
                    <td>{power_opt['die_area_mm2']}</td>
                    <td style="color:green;"><b>{power_opt['power_efficiency_pjb']}</b></td>
                    <td>{power_opt['link_eye_margin_ui']}</td>
                </tr>
                <tr>
                    <td><b>Performance</b></td>
                    <td>{perf_opt['design_name']}</td>
                    <td>{perf_opt['die_area_mm2']}</td>
                    <td>{perf_opt['power_efficiency_pjb']}</td>
                    <td style="color:blue;"><b>{perf_opt['link_eye_margin_ui']}</b></td>
                </tr>
                <tr>
                    <td><b>Density</b></td>
                    <td>{density_opt['design_name']}</td>
                    <td style="color:red;"><b>{density_opt['die_area_mm2']}</b></td>
                    <td>{density_opt['power_efficiency_pjb']}</td>
                    <td>{density_opt['link_eye_margin_ui']}</td>
                </tr>
            </table>
        </div>
    </div>
    """

    os.makedirs(os.path.dirname(output_html), exist_ok=True)
    plot_html = fig.to_html(full_html=False, include_plotlyjs='cdn')
    
    with open(output_html, "w") as f:
        f.write("<html><body>")
        f.write(plot_html)
        f.write(key_html)
        f.write(summary_html)
        f.write("</body></html>")
        
    print(f"✅ Dashboard saved to {output_html}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', type=str, default='reports/pareto_data.csv')
    parser.add_argument('--out', type=str, default='reports/pareto_dashboard.html')
    args = parser.parse_args()
    visualize_pareto(args.csv, args.out)
