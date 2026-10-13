package main

import (
	"os"
	"vms.local/platform/analysis/internal/app"
	"vms.local/platform/internal/httpapi"
)

func main() { os.Exit(httpapi.Main(app.New)) }
