# FoxyApply

**Stop copy-pasting the same answers into 50 LinkedIn Easy Apply forms.**

FoxyApply runs a real browser, fills out applications with your info, and submits them while you do literally anything else.

![Demo](demo.gif)

## Quick Start

```bash
# Or build from source
go install github.com/wailsapp/wails/v3/cmd/wails3@latest
git clone https://github.com/pypesdev/foxyapply && cd foxyapply
wails3 build
```

## How It Works

1. Add your LinkedIn credentials and basic info (phone, location, experience)
2. Set target job titles and locations
3. Click **Start** — watch it apply to jobs in a real browser window

## Development

This project is built with [Wails 3](https://v3.wails.io/).

### Prerequisites

1. **Go 1.23+**
   ```bash
   # macOS
   brew install go

   # or download from https://go.dev/dl/
   ```

2. **Node.js 20+**
   ```bash
   # macOS
   brew install node

   # or download from https://nodejs.org/
   ```

3. **Wails 3 CLI**
   ```bash
   go install github.com/wailsapp/wails/v3/cmd/wails3@latest
   ```
### Run in Development Mode
### Activate python virtual environment
```bash
python3 -m venv venv
```
```bash
source venv/bin/activate
```
On Windows use:
```bash
python -m venv venv
```bash
venv\Scripts\activate
```

```
source venv/bin/activate
```

### Install python dependencies
```
pip install -r requirements.txt
```

```bash
wails3 dev
```

### Build for Production

```bash
wails3 build
```
The production executable will be created in the `build` directory.


## Troubleshooting

# wails3 dev hangs after generating bindings
- ctrl+c will show you error - make sure to install requirements with `pip install -r requirements.txt` and make sure pyinstaller is in $PATH


### Testing

### Run go unit tests
```bash
go test ./...
```

### to make changes to the easyapplybot.py
rebuild the pyinstaller exe binary that places it in the build/ dir with:
`wails3 dev`

## License

MIT
