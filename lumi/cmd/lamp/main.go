package main

import (
	"flag"
	"fmt"
	"log"
	"log/slog"

	"go-lamp.autonomous.ai/lib/logger"
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

	logger.Init(slog.LevelDebug)

	srv, err := server.InitializeServer()
	if err != nil {
		log.Fatal("initialize server: ", err)
	}
	if err := srv.Serve(func() {}); err != nil {
		log.Fatal("http server: ", err)
	}
}
