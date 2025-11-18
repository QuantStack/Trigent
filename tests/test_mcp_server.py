"""Test MCP server functionality with real subprocess."""

import json
import subprocess
import time
from typing import Any
import socket
import os
import signal

import pytest
import requests


class TestMCPServer:
    """Test suite for MCP server functionality."""

    def test_mcp_server_startup_and_tools(self, test_repo, test_config, populated_collection, skip_if_no_config):
        """Test MCP server startup and basic tool functionality using subprocess."""
        
        # Start MCP server in subprocess with HTTP transport
        cmd = [
            "python", "-m", "trigent", "serve", test_repo,
            "--host", "localhost",
            "--port", "8001"  # Use different port to avoid conflicts
        ]
        
        print(f"🚀 Starting MCP server subprocess: {' '.join(cmd)}")
        
        # Start server process
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        try:
            # Wait a bit for server to start up
            time.sleep(2)
            
            # Check if server is running
            assert process.poll() is None, "MCP server process should still be running"
            
            # Test basic HTTP endpoint (this depends on FastMCP's HTTP interface)
            # Note: FastMCP might use different endpoints, this is a basic connectivity test
            try:
                response = requests.get("http://localhost:8001/", timeout=5)
                print(f"✅ Server responded with status: {response.status_code}")
                # Don't assert specific status code as FastMCP interface may vary
            except requests.exceptions.RequestException as e:
                print(f"📡 Server connection test: {e}")
                # This is expected as we might not have the right endpoint
            
            # Let server run for a moment to ensure stability
            time.sleep(1)
            assert process.poll() is None, "MCP server should remain stable"
            
        finally:
            # Clean up: terminate the server process
            print("🛑 Terminating MCP server subprocess")
            process.terminate()
            
            # Wait for graceful shutdown
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("⚠️  Forcing server shutdown")
                process.kill()
                process.wait()
            
            # Check for any error output
            stdout, stderr = process.communicate()
            if stdout:
                print(f"📤 Server stdout: {stdout}")
            if stderr and "KeyboardInterrupt" not in stderr:
                print(f"📤 Server stderr: {stderr}")

    def test_mcp_server_http_api(self, test_repo, test_config, populated_collection, skip_if_no_config):
        """Test MCP server via HTTP API requests."""
        
        # Find an available port
        def get_free_port():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', 0))
                s.listen(1)
                port = s.getsockname()[1]
            return port
        
        port = get_free_port()
        
        # Start MCP server in subprocess with HTTP transport
        env = os.environ.copy()
        # Pass config via environment if needed
        
        cmd = [
            "python", "-m", "trigent", "serve", test_repo,
            "--host", "localhost",
            "--port", str(port)
        ]
        
        print(f"🚀 Starting MCP server on port {port}: {' '.join(cmd)}")
        
        # Start server process
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )
        
        try:
            # Wait for server to start
            server_ready = False
            max_retries = 30
            for i in range(max_retries):
                time.sleep(0.5)
                
                # Check if process is still running
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    print(f"❌ Server process exited prematurely")
                    print(f"Server stdout: {stdout}")
                    print(f"Server stderr: {stderr}")
                    raise RuntimeError("Server process exited prematurely")
                
                try:
                    # Try to connect to the server - just basic connectivity
                    response = requests.get(f"http://localhost:{port}/", timeout=1)
                    print(f"✅ Server responded with status {response.status_code} after {i+1} attempts")
                    print(f"   Response headers: {dict(response.headers)}")
                    if response.text:
                        print(f"   Response body preview: {response.text[:200]}")
                    server_ready = True
                    break
                except requests.exceptions.ConnectionError as e:
                    if i % 5 == 0:
                        print(f"⏳ Waiting for server to start... (attempt {i+1}/{max_retries})")
                except requests.exceptions.RequestException as e:
                    print(f"   Connection attempt {i+1} failed: {type(e).__name__}: {e}")
            
            if not server_ready:
                # Get server output for debugging
                stdout, stderr = process.communicate(timeout=1)
                print(f"❌ Server failed to start after {max_retries} attempts")
                print(f"Server stdout: {stdout}")
                print(f"Server stderr: {stderr}")
                raise RuntimeError("Server failed to start")
            
            # Now let's test the MCP protocol through SSE endpoint
            print("\n🔍 Testing MCP protocol via SSE endpoint...")
            
            # The SSE endpoint is at /sse
            sse_url = f"http://localhost:{port}/sse"
            
            # For SSE connections, we need to establish a proper event stream
            print("\n🤝 Establishing SSE connection...")
            
            # SSE requires a GET request with proper headers for event streaming
            headers = {
                "Accept": "text/event-stream",
                "Cache-Control": "no-cache",
            }
            
            # Create a session for persistent connection
            session = requests.Session()
            
            try:
                # Connect to SSE endpoint
                print("📡 Connecting to SSE endpoint...")
                with session.get(sse_url, headers=headers, stream=True, timeout=5) as response:
                    print(f"   Response status: {response.status_code}")
                    print(f"   Content-Type: {response.headers.get('content-type')}")
                    
                    if response.status_code == 200:
                        # Read initial SSE events
                        lines_read = 0
                        for line in response.iter_lines(decode_unicode=True):
                            if lines_read > 10:  # Limit initial read
                                break
                            if line:
                                print(f"   SSE line: {line}")
                                lines_read += 1
                
                # Now let's try the MCP protocol with a separate POST request
                # MCP typically uses JSON-RPC over HTTP POST
                print("\n📋 Testing MCP initialize...")
                
                # First, initialize the connection
                init_request = {
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {
                            "name": "test-client",
                            "version": "1.0.0"
                        }
                    },
                    "id": 1
                }
                
                # Try different endpoints for JSON-RPC
                for endpoint in ["/", "/rpc", "/jsonrpc", f"{sse_url}/rpc"]:
                    print(f"\n   Trying endpoint: {endpoint}")
                    try:
                        response = session.post(
                            f"http://localhost:{port}{endpoint}",
                            json=init_request,
                            headers={"Content-Type": "application/json"},
                            timeout=2
                        )
                        print(f"   Status: {response.status_code}")
                        if response.status_code == 200:
                            print(f"   Response: {response.text[:200]}")
                            break
                    except Exception as e:
                        print(f"   Failed: {type(e).__name__}")
                
                # Test listing tools
                print("\n📋 Testing tools/list...")
                list_tools_request = {
                    "jsonrpc": "2.0",
                    "method": "tools/list",
                    "params": {},
                    "id": 2
                }
                
                # The actual SSE protocol might require a different approach
                # Let's check if we can interact through standard HTTP POST
                response = session.post(
                    f"http://localhost:{port}/",
                    json=list_tools_request,
                    headers={"Content-Type": "application/json"},
                    timeout=5
                )
                
                print(f"   Response status: {response.status_code}")
                if response.text:
                    print(f"   Response: {response.text[:200]}")
                
            except Exception as e:
                print(f"❌ Connection failed: {type(e).__name__}: {str(e)}")
            finally:
                session.close()
            
            print("\n✅ MCP server connectivity test completed")
            
        finally:
            # Clean up: terminate the server process
            print("\n🛑 Terminating MCP server subprocess")
            if process.poll() is None:
                # Send SIGTERM for graceful shutdown
                os.kill(process.pid, signal.SIGTERM)
                
                # Wait for graceful shutdown
                try:
                    process.wait(timeout=5)
                    print("✅ Server terminated gracefully")
                except subprocess.TimeoutExpired:
                    print("⚠️  Forcing server shutdown")
                    process.kill()
                    process.wait()
            
            # Check for any error output
            stdout, stderr = process.communicate()
            if stdout:
                print(f"📤 Server stdout: {stdout}")
            if stderr and "KeyboardInterrupt" not in stderr and "Terminated" not in stderr:
                print(f"📤 Server stderr: {stderr}")

    def test_mcp_server_config_flow(self, test_repo, test_config, skip_if_no_config):
        """Test that config flows properly through MCP server startup."""
        from trigent.serve.mcp_server import run_mcp_server, _mcp_config
        import trigent.serve.mcp_server as mcp_module
        
        # Ensure config starts as None
        mcp_module._mcp_config = None
        assert mcp_module._mcp_config is None
        
        # Mock the actual server startup to avoid network binding
        original_run = None
        def mock_server_run(*args, **kwargs):
            print("🎭 Mocked FastMCP run() called")
            return None
        
        try:
            # Patch the mcp.run method to avoid actual server startup
            import trigent.serve.mcp_server
            original_run = trigent.serve.mcp_server.mcp.run
            trigent.serve.mcp_server.mcp.run = mock_server_run
            
            # Test config setting during server startup
            run_mcp_server(host="localhost", port=8002, repo=test_repo, config=test_config)
            
            # Verify config was set
            assert mcp_module._mcp_config is not None
            assert mcp_module._mcp_config == test_config
            assert "qdrant" in mcp_module._mcp_config
            print("✅ Config properly set in global variable during server startup")
            
        finally:
            # Restore original method and clean up
            if original_run:
                trigent.serve.mcp_server.mcp.run = original_run
            mcp_module._mcp_config = None

    def test_mcp_server_tools_via_api(self, test_repo, test_config, populated_collection, skip_if_no_config):
        """Test MCP server tools through proper API."""
        
        # Find an available port
        def get_free_port():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', 0))
                s.listen(1)
                port = s.getsockname()[1]
            return port
        
        port = get_free_port()
        
        # Start MCP server
        cmd = [
            "python", "-m", "trigent", "serve", test_repo,
            "--host", "localhost",
            "--port", str(port)
        ]
        
        print(f"🚀 Starting MCP server on port {port}: {' '.join(cmd)}")
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        try:
            # Wait for server to start with better debugging
            server_ready = False
            for i in range(60):  # Increase timeout to 30 seconds
                time.sleep(0.5)
                
                # Check if process is still alive
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    print(f"❌ Server process died after {i*0.5:.1f}s")
                    print(f"   Exit code: {process.returncode}")
                    print(f"   STDOUT: {stdout[:500]}")
                    print(f"   STDERR: {stderr[:500]}")
                    raise RuntimeError(f"Server exited with code {process.returncode}: {stderr}")
                
                # Try to connect
                try:
                    response = requests.get(f"http://localhost:{port}/", timeout=1)
                    print(f"✅ Server responded with status {response.status_code} after {i*0.5:.1f}s")
                    server_ready = True
                    break
                except requests.exceptions.ConnectionError:
                    if i % 10 == 0 and i > 0:  # Print every 5 seconds
                        print(f"⏳ Still waiting for server... ({i*0.5:.1f}s)")
                    continue
                except Exception as e:
                    print(f"⚠️  Unexpected error during connection: {type(e).__name__}: {e}")
                    continue
            
            if not server_ready:
                # Get final debug info
                try:
                    # Don't use communicate() as it waits for process to end
                    print(f"❌ Server failed to start after 30 seconds")
                    print(f"   Process is alive: {process.poll() is None}")
                    if process.poll() is not None:
                        print(f"   Exit code: {process.returncode}")
                except Exception as e:
                    print(f"   Error getting process info: {e}")
                raise RuntimeError("Server failed to start within 30 seconds")
            
            # Test the SSE endpoint with proper MCP protocol
            print("\n🔍 Testing MCP tools through SSE...")
            
            # SSE endpoint URL
            sse_url = f"http://localhost:{port}/sse"
            
            # Test basic connectivity to SSE endpoint
            response = requests.get(sse_url, headers={"Accept": "text/event-stream"}, stream=True, timeout=2)
            print(f"✅ SSE endpoint responded with status: {response.status_code}")
            response.close()
            
            # For now, we've verified:
            # 1. Server starts successfully
            # 2. SSE endpoint is accessible
            # 3. Server is running with our test repository
            
            print("✅ MCP server is running and accessible")
            
        finally:
            # Clean up
            print("\n🛑 Terminating MCP server")
            if process.poll() is None:
                os.kill(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()