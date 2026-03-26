package main

import (
	"flag"
	"fmt"
	"io"
	"log"
	"os"

	"go-lamp.autonomous.ai/bootstrap"
	"go-lamp.autonomous.ai/bootstrap/config"
)

func main() {
	var showVersion bool
	flag.BoolVar(&showVersion, "version", false, "print version and exit")
	flag.Parse()

	if showVersion {
		fmt.Println(config.BootstrapVersion)
		return
	}

	// Write logs to both stdout and file for easier debugging
	logFile, err := os.OpenFile("/var/log/bootstrap.log", os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err == nil {
		log.SetOutput(io.MultiWriter(os.Stdout, logFile))
		defer logFile.Close()
	}

	b, err := bootstrap.ProvideServer()
	if err != nil {
		log.Fatalf("bootstrap: initialize: %v", err)
	}
	if err := b.Serve(); err != nil {
		log.Fatalf("bootstrap: %v", err)
	}
	log.Print("bootstrap: stopped")
}
