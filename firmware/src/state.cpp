#include "state.h"

State state;

namespace {
SemaphoreHandle_t mutex;
}

void stateBegin() { mutex = xSemaphoreCreateRecursiveMutex(); }

State::Lock::Lock() { xSemaphoreTakeRecursive(mutex, portMAX_DELAY); }

State::Lock::~Lock() { xSemaphoreGiveRecursive(mutex); }
