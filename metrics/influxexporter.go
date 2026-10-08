package metrics

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/InfluxCommunity/influxdb3-go/v2/influxdb3"
)

type InfluxExporter struct {
	client   *influxdb3.Client
	database string
	runID    int
}

func getNextRunID(client *influxdb3.Client, database string) (int, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// Query for the highest run_id
	query := `SELECT DISTINCT run_id FROM simulation_metrics`
	iterator, err := client.Query(ctx, query)

	if err != nil {
		// No existing data or table doesn't exist, start with run_id 0
		fmt.Println("No existing data found, starting with run_id 0")
		return 0, nil
	}

	maxRunID := -1
	for iterator.Next() {
		stringData := iterator.Value()["run_id"].(string)
		currRunID, err := strconv.Atoi(stringData)
		if err != nil {
			continue
		}
		if currRunID > maxRunID {
			maxRunID = currRunID
		}
	}

	nextRunID := maxRunID + 1
	fmt.Printf("Found existing run_id data, using run_id: %d\n", nextRunID)
	return nextRunID, nil
}

func NewInfluxExporter(serverURL, token, database string) (*InfluxExporter, error) {
	// Create InfluxDB v3 client
	client, err := influxdb3.New(influxdb3.ClientConfig{
		Host:     serverURL,
		Token:    token,
		Database: database,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to create InfluxDB client: %w", err)
	}

	// Get the next run ID
	nextRunID, err := getNextRunID(client, database)
	if err != nil {
		return nil, fmt.Errorf("failed to get next run ID: %w", err)
	}

	exporter := &InfluxExporter{
		client:   client,
		database: database,
		runID:    nextRunID,
	}

	fmt.Printf("Starting simulation with run_id: %d\n", nextRunID)
	return exporter, nil
}

func (ie *InfluxExporter) WriteMultipleMetrics(metrics map[string]float64, tags map[string]string, simulationTime float64) error {
	// Convert simulation time to timestamp

	timestamp := time.Unix(int64(simulationTime), int64((simulationTime-float64(int64(simulationTime)))*1e9))
	var points []*influxdb3.Point

	for metricName, value := range metrics {
		// Create tags for each metric
		metricTags := make(map[string]string)
		for k, v := range tags {
			metricTags[k] = v
		}
		metricTags["metric"] = metricName
		metricTags["run_id"] = strconv.Itoa(ie.runID)

		// Create point with simulation time
		point := influxdb3.NewPoint("simulation_metrics", metricTags, map[string]any{
			"value": value,
		}, timestamp)

		points = append(points, point)
	}

	// Write all points
	return ie.client.WritePoints(context.Background(), points)
}

func (ie *InfluxExporter) Close() {
	// Close client
	ie.client.Close()
}

func (ie *InfluxExporter) TestConnection() error {
	// Test connection by attempting to write a test point
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	// Create a simple test point
	testPoint := influxdb3.NewPoint("connection_test",
		map[string]string{"test": "true"},
		map[string]any{"value": 1.0},
		time.Now())

	// Try to write the test point
	err := ie.client.WritePoints(ctx, []*influxdb3.Point{testPoint})
	if err != nil {
		return fmt.Errorf("influxdb connection test failed: %w", err)
	}

	return nil
}
