import json
import os
import pandas as pd

class IndustrialToolIngestor:
    """
    🚀 v5.8.0 Industrial Data Bridge
    Parses intermediary outputs from Ansys, Cadence, and Siemens.
    Enables 3DIC-X to use 'Golden' production data as a reference.
    """
    def __init__(self, workspace_path="external_references/"):
        self.workspace = workspace_path
        os.makedirs(self.workspace, exist_ok=True)

    def ingest_ansys_thermal(self, csv_path):
        """Parses Ansys Icepak Monitor Point exports."""
        print(f"📥 Ingesting Ansys Icepak Monitor Data: {csv_path}")
        try:
            df = pd.read_csv(csv_path)
            # Standard Icepak CSV contains [Time, Temp_Point_1, Temp_Point_2, ...]
            # We map this to our ROI coordinate system
            avg_temp = df.iloc[:, 1:].mean().mean()
            peak_temp = df.iloc[:, 1:].max().max()
            
            return {
                "source": "Ansys Icepak",
                "avg_temp_c": round(float(avg_temp), 2),
                "peak_temp_c": round(float(peak_temp), 2),
                "samples": len(df)
            }
        except Exception as e:
            return {"error": f"Failed to parse Ansys CSV: {str(e)}"}

    def ingest_cadence_netlist(self, sp_path):
        """Reads a Spectre/SPICE netlist to extract structural 'In-File' constraints."""
        print(f"📥 Ingesting Cadence Structural Reference: {sp_path}")
        try:
            with open(sp_path, 'r') as f:
                content = f.read()
            
            # Extract subcircuits count as a complexity proxy
            subckt_count = content.count(".subckt")
            # Extract temperature setting if present
            temp_match = [line for line in content.split('\n') if ".temp" in line.lower()]
            
            return {
                "source": "Cadence Spectre",
                "subcircuits_detected": subckt_count,
                "reference_temp": temp_match[0] if temp_match else "Default"
            }
        except Exception as e:
            return {"error": f"Failed to read netlist: {str(e)}"}

if __name__ == "__main__":
    # Example usage for integration check
    ingestor = IndustrialToolIngestor()
    # Mock data generation for test
    mock_csv = "external_references/ansys_thermal_trace.csv"
    with open(mock_csv, "w") as f:
        f.write("Time,Point1,Point2\n0,25,25\n100,104.2,103.8")
    
    result = ingestor.ingest_ansys_thermal(mock_csv)
    print("Ingested Ansys Data:", json.dumps(result, indent=2))
