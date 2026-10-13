package main

import (
	"os"
	"vms.local/platform/internal/httpapi"
	"vms.local/platform/model/internal/app"
)

func main() { os.Exit(httpapi.Main(app.New)) }
