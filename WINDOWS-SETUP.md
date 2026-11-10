# Running PulseIQ on Windows

## You need

- Windows 10 or 11, 8 GB RAM or more, and about 10 GB of free disk space
- [Docker Desktop](https://www.docker.com/products/docker-desktop/), installed and running ("Engine running" in its window)

## First time (15-20 minutes)

1. Clone this repository (or unzip the shared copy) somewhere with a short path, for example `C:\PulseIQ`.
2. Start Docker Desktop and wait until it shows **Engine running**.
3. Double-click **`setup.bat`**.

Setup builds the Docker image, copies the bundled data into Docker, builds the warehouse, and opens
http://localhost:8501 in your browser. A fresh clone has no bundled data, so setup downloads the
dataset and trains the models instead (about 45 minutes).

If Windows shows "Windows protected your PC", click **More info**, then **Run anyway**.

## After that

| To | Do |
| --- | --- |
| Start the app | Double-click `start.bat` |
| Stop the app | Double-click `stop.bat` (your data is kept) |
| Rebuild everything from the raw dataset | In PowerShell: `.\setup.ps1 -FromScratch` (about 45 minutes, downloads 1.74 GB) |

## For the demo

Open the **Live** page, pick a day and press **Start**. A full day replays in about 2.5 minutes,
and the purchase-intent model scores shoppers as they browse.

## If something goes wrong

| Problem | Fix |
| --- | --- |
| "Docker Desktop is not running" | Start Docker Desktop, wait for "Engine running", run setup again |
| A step fails with "Killed" or exit code 137 | Docker ran out of memory. Close other apps and run setup again. If it still fails, create `C:\Users\<you>\.wslconfig` containing `[wsl2]` and `memory=6GB` on two lines, restart Docker Desktop, then run setup again |
| Port 8501 already in use | Close the other app using it, or stop it with `stop.bat` |
| Anything else | Run setup again |

Running setup again is safe: it never overwrites data already in Docker. It rebuilds the warehouse, so it takes about 10 minutes.
