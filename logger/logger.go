package logger

import (
	"fmt"
	"io"
	"os"
	"sync"

	"github.com/sirupsen/logrus"
)

var (
	log  *logrus.Logger
	once sync.Once
)

// Initialize sets up the logger. Call this once in the main package.
func Initialize(debug bool, logPath string) {
	once.Do(func() {
		file, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0666)
		if err != nil {
			logrus.Fatalf("Failed to open log file '%s': %v", logPath, err)
		}
		multiWriter := io.MultiWriter(os.Stdout, file)

		log = logrus.New()
		log.SetOutput(multiWriter) // Output to both standard out and file
		log.SetFormatter(&orderedJSONFormatter{})
		if debug {
			log.SetLevel(logrus.DebugLevel)
		} else {
			log.SetLevel(logrus.InfoLevel)
		}
	})
}

// GetLogger provides a logger instance enriched with simulation time.
func GetLogger(simTime float64) *logrus.Entry {
	return log.WithField("simTime", fmt.Sprintf("%.5f", simTime))
}
