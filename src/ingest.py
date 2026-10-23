from pathlib import Path
import requests

# ---- parameters: the only lines you edit to get other data ----
DATASET_ID = "4zgsckxpdy"
VERSION = 2
TARGET_DIR = Path("data/raw") / f"v{VERSION}"

API_URL = (f"https://data.mendeley.com/public-api/datasets/"
           f"{DATASET_ID}/files?folder_id=root&version={VERSION}")


def main():
    # 1. Create TARGET_DIR if it doesn't exist
    #    hint: TARGET_DIR.mkdir(parents=True, exist_ok=True)
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Call the API and turn the JSON into a Python list
    #    hint: requests.get(API_URL).json()
  
    files = requests.get(API_URL).json()
    print(len(files))

    for file in files:
        local_path = TARGET_DIR / file["filename"]
        if local_path.exists() and local_path.stat().st_size == file["size"]:
            print("skipping", file["filename"])
            continue
        else:
            download_url = file["content_details"]["download_url"]
            response = requests.get(download_url)
            response.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(response.content)
            print(f"Downloaded {file['filename']} ({file['size']} bytes)")   

    # 3. Loop over the list. For each file:
    #    a) local path = TARGET_DIR / file["filename"]
    #    b) if that path exists AND its size equals file["size"]:
    #         print "skipping", then continue   (idempotent!)
    #    c) otherwise download content_details -> download_url
    #       and save the bytes to the local path
    #    d) print the filename and size so you can see progress
    pass


if __name__ == "__main__":
    main()