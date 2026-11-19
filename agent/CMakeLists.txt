# Copyright (c) 2026-2027 zbc
# URC 协议库（liburc_protocol）与向量测试；mock/参考 Agent 在后续增量加入。
cmake_minimum_required(VERSION 3.22)
project(urc_agent LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(OpenSSL REQUIRED)

add_library(urc_protocol
    src/crc32c.cpp
    src/frame.cpp
    src/crypto.cpp
    src/messages.cpp
)
target_include_directories(urc_protocol PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_link_libraries(urc_protocol PUBLIC OpenSSL::Crypto)
target_compile_options(urc_protocol PRIVATE -Wall -Wextra -Wpedantic -Wno-deprecated-declarations)

enable_testing()

add_executable(urc_vectors tests/test_vectors.cpp)
target_include_directories(urc_vectors PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/third_party)
target_link_libraries(urc_vectors PRIVATE urc_protocol)
target_compile_definitions(urc_vectors PRIVATE
    URC_VECTORS_DIR="${CMAKE_CURRENT_SOURCE_DIR}/../protocol/vectors")
add_test(NAME urc_vectors COMMAND urc_vectors)
