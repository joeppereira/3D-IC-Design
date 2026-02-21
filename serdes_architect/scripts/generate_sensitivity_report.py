import pandas as pd
import numpy as np

def generate_sensitivity():
    print("📊 Generating Design Sensitivity Report...")
    csv_path = "reports/pareto_data.csv"
    if not os.path.exists(csv_path):
        print("Data not found.")
        return
        
    df = pd.read_csv(csv_path)
    
    # Calculate Correlation to "Quality of Result" (Margin / Power)
    # We define QOR = (Eye Margin * 10) - (Relative Cost * 2) - (Temp / 100)
    df['qor'] = (df['link_eye_margin_ui'] * 10) - (df['relative_cost'] * 2) - (df['thermal_tj_c'] / 100.0)
    
    # Simple Sensitivity: Correlation of variables to QOR
    correlations = df[['power_efficiency_pjb', 'die_area_mm2', 'thermal_tj_c', 'relative_cost']].corrwith(df['qor'])
    
    with open("reports/sensitivity_analysis.md", "w") as f:
        f.write("# 📈 Design Sensitivity Analysis\n\n")
        f.write("This report identifies which architectural levers had the greatest impact on the final design score.\n\n")
        f.write("| Architectural Lever | Sensitivity Impact | Direction |\n")
        f.write("| :--- | :--- | :--- |\n")
        
        for lever, val in correlations.items():
            impact = "High" if abs(val) > 0.5 else "Medium"
            direction = "Positive (Increase to improve)" if val > 0 else "Negative (Decrease to improve)"
            f.write(f"| {lever.replace('_', ' ').title()} | {impact} ({abs(val):.2f}) | {direction} |\n")
            
        f.write("\n## 💡 Key Architectural Takeaway\n")
        max_lever = correlations.abs().idxmax().replace('_', ' ').title()
        f.write(f"For this project, **{max_lever}** was the dominant factor in achieving sign-off. Optimizing this variable first will yield the fastest convergence in future iterations.")

    print("✅ Sensitivity analysis saved to reports/sensitivity_analysis.md")

if __name__ == "__main__":
    import os
    generate_sensitivity()
