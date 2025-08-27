# kigaroo-image-downloader
A quick and dirty download script for images from kigaroo.de image albums.

The script downloads the images for all available albums and adds some EXIF meta data (date based on kigaroo and GPS location based on the config file).

## Install
Create a venv, clone the repo.

The script uses a headless chrominum for downloading via playwright. So you'll have to install playwright.

Install some python dependencies:
```bash
pip install exif playwright pathvalidate
```
Copy the `config.example.json` to `config.json` and modify it accordingly.

## Usage
Just run the script.
```bash
python kigaroo-downloader.py
```

## Limitations
Currently the script will only download albums from the default group.
