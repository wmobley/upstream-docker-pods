#!/bin/bash

# Simple test script to verify Tapis authentication is working
# Usage: ./test_tapis_auth.sh [BASE_URL]
# Example: ./test_tapis_auth.sh http://localhost:8000

BASE_URL=${1:-http://localhost:8000}
API_URL="${BASE_URL}/api/v1"

echo "🔍 Testing Tapis Authentication"
echo "================================"
echo "Base URL: ${BASE_URL}"
echo ""

# Test 1: Without Tapis headers (should work if dev middleware is enabled)
echo "Test 1: Request WITHOUT Tapis headers"
echo "--------------------------------------"
response=$(curl -s -w "\nHTTP_STATUS:%{http_code}" "${API_URL}/campaigns")
http_status=$(echo "$response" | grep "HTTP_STATUS" | cut -d: -f2)
body=$(echo "$response" | sed '$d')

if [ "$http_status" = "200" ]; then
    echo "✅ Success (HTTP 200)"
    echo "   → Dev middleware is likely enabled"
elif [ "$http_status" = "401" ]; then
    echo "⚠️  Unauthorized (HTTP 401)"
    echo "   → Dev middleware is likely disabled"
    echo "   → Or no JWT token provided"
else
    echo "❌ Unexpected status: HTTP ${http_status}"
fi
echo ""

# Test 2: With explicit Tapis headers
echo "Test 2: Request WITH Tapis headers"
echo "-----------------------------------"
response=$(curl -s -w "\nHTTP_STATUS:%{http_code}" \
  -H "X-Tapis-Username: testuser" \
  -H "X-Tapis-Tenant: tacc" \
  -H "X-Tapis-Site: tacc" \
  "${API_URL}/campaigns")
http_status=$(echo "$response" | grep "HTTP_STATUS" | cut -d: -f2)

if [ "$http_status" = "200" ]; then
    echo "✅ Success (HTTP 200)"
    echo "   → Tapis authentication is working!"
elif [ "$http_status" = "401" ]; then
    echo "❌ Unauthorized (HTTP 401)"
    echo "   → Tapis authentication may not be configured correctly"
else
    echo "❌ Unexpected status: HTTP ${http_status}"
fi
echo ""

# Test 3: Check if endpoint exists to inspect headers
echo "Test 3: Header Inspection Endpoint (if available)"
echo "--------------------------------------------------"
response=$(curl -s -w "\nHTTP_STATUS:%{http_code}" \
  -H "X-Tapis-Username: testuser" \
  -H "X-Tapis-Tenant: tacc" \
  -H "X-Tapis-Site: tacc" \
  "${API_URL}/test/auth" 2>/dev/null)
http_status=$(echo "$response" | grep "HTTP_STATUS" | cut -d: -f2)
body=$(echo "$response" | sed '$d')

if [ "$http_status" = "200" ]; then
    echo "✅ Test endpoint found"
    echo "$body" | python3 -m json.tool 2>/dev/null || echo "$body"
elif [ "$http_status" = "404" ]; then
    echo "ℹ️  Test endpoint not found (optional)"
else
    echo "Status: HTTP ${http_status}"
fi
echo ""

# Summary
echo "================================"
echo "📋 Summary"
echo "================================"
echo "To enable dev middleware:"
echo "  1. Add to .env: ENABLE_DEV_TAPIS_HEADERS=true"
echo "  2. Restart backend"
echo ""
echo "To test with different users:"
echo "  export DEV_TAPIS_USERNAME=myuser"
echo "  export DEV_TAPIS_TENANT=mytenant"
echo ""
echo "For full docs, see: TAPIS_AUTH_TESTING.md"
