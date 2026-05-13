import pandas as pd

# Read the CSV file
df = pd.read_csv("results/rtt_comparison.csv")

# Filter rows where dqn_avg_rtt_ms < hop_avg_rtt_ms
filtered_df = df[df["dqn_avg_rtt_ms"] < df["hop_avg_rtt_ms"]]

# Calculate averages for numeric columns
averages = filtered_df.mean(numeric_only=True)

# Print filtered rows
print("Filtered Rows:")
print(filtered_df)
print(f"Row Count: {len(filtered_df)}")

# Print averages
print("\nColumn Averages:")
print(averages)