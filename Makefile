# Go variables
GO_CMD := go
GO_BUILD := $(GO_CMD) build
GO_RUN := $(GO_CMD) run
TARGET := network-simulator 

# Profiling variables
CPU_PROFILE_OUT := go-simulator.prof
MEM_PROFILE_OUT := mem.prof
RUN_ARGS ?=

# Default target: Build the application
build:
	@echo "Building the application..."
	$(GO_BUILD) -o $(TARGET) .

# Run the application and measure execution time
run: build
	@echo "Running the application..."
	./$(TARGET) $(RUN_ARGS) > /dev/null

# Run the application and measure execution time
profile: build
	@echo "Profiling the application..."
	time ./$(TARGET) -cpuprofile=$(CPU_PROFILE_OUT) > /dev/null

time: build
	@echo "Timing the application..."
	time ./$(TARGET) > /dev/null
# 	time ./$(TARGET)

run-override: build
	@echo "Running the application with explicit config/log paths..."
	./$(TARGET) -config=./conf/simulation.yaml -log=./simlogs/app.log > /dev/null

batch-example: build
	@echo "Running example experiment batch..."
	python3 ./experiments/batch_runner.py --experiment ./conf/experiments/batch-example.yaml

batch-dry-run:
	@echo "Previewing experiment combinations..."
	python3 ./experiments/batch_runner.py --experiment ./conf/experiments/batch-example.yaml --dry-run

# Clean generated files
clean:
	@echo "Cleaning up..."
	rm -f $(TARGET) $(CPU_PROFILE_OUT) $(MEM_PROFILE_OUT)

obs-restart:
	cd ./docker && docker compose -f docker-compose.yml down
	cd ./docker && docker compose -f docker-compose.yml up -d

obs-down:
	cd ./docker && docker compose -f docker-compose.yml down