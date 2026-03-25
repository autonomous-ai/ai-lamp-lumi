package main

import (
	"flag"
	"fmt"
	"log"

	"go-lamp.autonomous.ai/server"
	"go-lamp.autonomous.ai/server/config"
)

func main() {
	var showVersion bool
	flag.BoolVar(&showVersion, "version", false, "print version and exit")
	flag.Parse()

	if showVersion {
		fmt.Println(config.InternVersion)
		return
	}

	srv, err := server.InitializeServer()
	if err != nil {
		log.Fatal("initialize server: ", err)
	}
	if err := srv.Serve(func() {}); err != nil {
		log.Fatal("http server: ", err)
	}
}
