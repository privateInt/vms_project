package main

import (
	"os"
	"vms.local/platform/internal/httpapi"
	"vms.local/platform/operation/internal/app"
)

func main() { os.Exit(httpapi.Main(app.New)) }
