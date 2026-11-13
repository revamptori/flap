package main
import (
	"fmt"
	"github.com/gin-gonic/gin"
)
func main() {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())
	r.GET("/", func(c *gin.Context) { c.String(200, "Hello, Gin!") })
	r.GET("/hello/:name", func(c *gin.Context) { c.String(200, "Hello, %s!", c.Param("name")) })
	r.GET("/user/:id", func(c *gin.Context) { c.JSON(200, gin.H{"id": c.Param("id"), "name": "Ada"}) })
	r.POST("/echo", func(c *gin.Context) {
		var body map[string]interface{}
		if err := c.ShouldBindJSON(&body); err != nil { c.JSON(200, gin.H{}); return }
		c.JSON(200, body)
	})
	r.GET("/search", func(c *gin.Context) { c.JSON(200, gin.H{"q": c.Query("q")}) })
	r.GET("/json", func(c *gin.Context) {
		items := make([]int, 3000)
		for i := range items { items[i] = i }
		c.JSON(200, gin.H{"message": "hello", "items": items, "nested": gin.H{"a": "b", "count": 3000}})
	})
	for i := 0; i < 500; i++ {
		path := fmt.Sprintf("/dummy_%d", i)
		idx := i
		r.GET(path, func(c *gin.Context) { c.String(200, "dummy %d", idx) })
	}
	r.Run("127.0.0.1:5002")
}
