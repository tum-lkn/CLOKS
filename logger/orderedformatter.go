package logger

import (
	"bytes"
	"encoding/json"
	"sort"
	"strings"

	"github.com/sirupsen/logrus"
)

type orderedJSONFormatter struct{}

func (f *orderedJSONFormatter) Format(entry *logrus.Entry) ([]byte, error) {
	var b bytes.Buffer
	b.WriteByte('{')

	appendJSONField := func(key string, value any, first bool) error {
		if !first {
			b.WriteByte(',')
		}

		keyBytes, err := json.Marshal(key)
		if err != nil {
			return err
		}
		valueBytes, err := json.Marshal(value)
		if err != nil {
			return err
		}

		b.Write(keyBytes)
		b.WriteByte(':')
		b.Write(valueBytes)
		return nil
	}

	// Fixed field order: simTime, msg, other fields, time, level.
	first := true

	if simTime, ok := entry.Data["simTime"]; ok {
		if err := appendJSONField("simTime", simTime, first); err != nil {
			return nil, err
		}
		first = false
	}

	if err := appendJSONField("msg", entry.Message, first); err != nil {
		return nil, err
	}
	first = false

	extraKeys := make([]string, 0, len(entry.Data))
	for k := range entry.Data {
		if k == "simTime" {
			continue
		}
		extraKeys = append(extraKeys, k)
	}
	sort.Strings(extraKeys)

	for _, key := range extraKeys {
		if err := appendJSONField(key, entry.Data[key], first); err != nil {
			return nil, err
		}
		first = false
	}

	if err := appendJSONField("time", entry.Time.Format("2006-01-02T15:04:05Z07:00"), first); err != nil {
		return nil, err
	}
	first = false

	if err := appendJSONField("level", entry.Level.String(), first); err != nil {
		return nil, err
	}
	first = false

	b.WriteByte('}')
	if !strings.HasSuffix(b.String(), "\n") {
		b.WriteByte('\n')
	}

	return b.Bytes(), nil
}
