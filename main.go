package main

import (
	"flag"
	"fmt"
	"network-simulator/core"
	"network-simulator/events"
	"network-simulator/logger"
	"network-simulator/server"

	"sync"

	"github.com/knadh/koanf/parsers/yaml"
	"github.com/knadh/koanf/providers/file"
	"github.com/knadh/koanf/v2"
)

// var cpuprofile = flag.String("cpuprofile", "", "write cpu profile to file")

func main() {

	configPath := flag.String("config", "./conf/simulation.yaml", "Path to the simulation configuration file")
	logPath := flag.String("log", "./simlogs/app.log", "Path to the simulation log file")
	flag.Parse()

	// ********** CONFIG **********
	var k = koanf.New(".")
	// Load the main configuration file
	if err := k.Load(file.Provider(*configPath), yaml.Parser()); err != nil {
		fmt.Printf("Error loading configuration file: %v\n", err)
	}

	// Initialize logger
	logger.Initialize(
		k.Bool("debug_logging"),
		*logPath,
	)

	// Initialize simulator
	simulator := core.NewSimulator(*configPath)

	// Ensure InfluxDB exporter is closed when simulation terminates
	if influxExporter := simulator.GetInfluxExporter(); influxExporter != nil {
		defer influxExporter.Close()
	}

	simulator.ScheduleEvent(events.NewSimStartEvent(0))

	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		simulator.Run()
	}()

	// Initialize HTTP Server
	enableSimServer := k.Bool("simulation_server.enabled")
	if enableSimServer {

		simServerPort := k.Int("simulation_server.port")
		httpServer := server.NewServer(simulator)

		wg.Add(1)
		go func() {
			defer wg.Done()
			httpServer.Start(fmt.Sprintf("%d", simServerPort))
		}()
	}

	wg.Wait()
}
