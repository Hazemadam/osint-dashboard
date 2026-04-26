import pandas as pd
# ... (your existing fetch logic)

def update_repo_data():
    df, status = fetch_data() # Your existing function
    if not df.empty:
        # Save as parquet (much smaller than CSV)
        df.to_parquet("nova_data.parquet") 
        print("Data updated successfully.")

if __name__ == "__main__":
    update_repo_data()
