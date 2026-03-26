package main

import (
	"flag"
	"fmt"
	"io"
	"log"
	"os"

	"go-lamp.autonomous.ai/server"
	"go-lamp.autonomous.ai/server/config"
)

func main() {
	var showVersion bool
	flag.BoolVar(&showVersion, "version", false, "print version and exit")
	flag.Parse()

	if showVersion {
		fmt.Println(config.LumiVersion)
		return
	}

	// Write logs to both stdout and file for easier debugging
	logFile, err := os.OpenFile("/var/log/lumi.log", os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err == nil {
		log.SetOutput(io.MultiWriter(os.Stdout, logFile))
		defer logFile.Close()
	}

	srv, err := server.InitializeServer()
	if err != nil {
		log.Fatal("initialize server: ", err)
	}
	if err := srv.Serve(func() {}); err != nil {
		log.Fatal("http server: ", err)
	}
}
